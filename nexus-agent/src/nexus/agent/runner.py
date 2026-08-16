"""AgentRunner — invoke the LangGraph graph and stream events.

Compiled graphs are stateless and cheap to rebuild; all state lives in the
Postgres checkpointer.  A fresh graph is built on every ``invoke()`` and
``resume()`` call.

Per-session concurrency is enforced via a Redis distributed lock with a
background heartbeat that extends the TTL every ``ttl/3`` seconds.  The
lock guards the ``astream`` execution window only — it is released when
``astream`` returns (whether completed, interrupted, or errored).  The
``resume()`` method acquires its own lock.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import uuid
from collections.abc import AsyncIterator
from copy import deepcopy as _deepcopy
from datetime import datetime, timezone
from typing import Any

import time as time_module

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from nexus.agent.graph import build_agent_graph
from nexus.agent.state import AgentState, _EPHEMERAL_FIELDS
from nexus.artifacts.graph import reset_artifact_graph
from nexus.config.settings import get_settings
from nexus.context.global_context import get_global_context, set_global_context
from nexus.context.session_context import SessionContext
from nexus.llm.client import LLMClient

# Module-level compiled graph cache — rebuilt once per process lifetime.
# Graph compilation (node/edge validation) is expensive (~30-50ms) and
# produces a stateless object — all run state lives in the checkpointer.
_compiled_graph: Any | None = None
_graph_lock = asyncio.Lock()
from nexus.observability.outcomes import InvocationOutcome, persist_outcome
from nexus.observability.tracing import get_tracer

# Track fire-and-forget background tasks so they aren't silently dropped
# when the request context tears down.  Tasks are removed automatically
# via a done_callback.  Drain on shutdown via drain_background_tasks().
_pending_bg_tasks: set[asyncio.Task] = set()


def _track_bg_task(task: asyncio.Task) -> None:
    """Hold a strong reference to a fire-and-forget task.

    Without this, the task can be garbage collected during request-context
    teardown before it finishes executing (a known asyncio footgun).
    """
    _pending_bg_tasks.add(task)
    task.add_done_callback(_pending_bg_tasks.discard)
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.pubsub import EventBus, agent_channel
from nexus.tools.executor import ToolExecutor

logger = structlog.get_logger("nexus.agent.runner")

# Guarded module-level tracer: OTel is optional — tracing must never break
# the run when the package is absent or unconfigured.
try:
    from opentelemetry.trace import get_tracer as _get_tracer  # noqa: PLC0415

    _NODE_TRACER = _get_tracer("nexus.agent.runner")
except Exception:
    _NODE_TRACER = None

AGENT_EVENT_TYPES = frozenset(
    {
        "plan_created",
        "tool_selected",
        "tool_call_started",
        "tool_call_completed",
        "clarification_needed",
        "clarification_question",
        "requirement_collected",
        "intent_extracted",
        "workflow_composing_progress",
        "validation_progress",
        "approval_checkpoint",
        "artifact_produced",
        "token_delta",
        "intermediate_preview",
        "final_response",
        "error",
        "reflection_result",
        "self_consistency_result",
    }
)

# Lua: atomically renew lock TTL only if we still own it
_RENEW_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""



class AgentEvent:
    """An event emitted during agent execution.

    Attributes:
        type: One of the ``AGENT_EVENT_TYPES``.
        payload: Event-specific data.
        ts: ISO-8601 timestamp of the event.
    """

    def __init__(self, type: str, payload: dict[str, Any]) -> None:  # noqa: A002
        self.type = type
        self.ts = datetime.now(timezone.utc).isoformat()
        self.payload = payload

    @classmethod
    def from_model(cls, model: Any) -> "AgentEvent":
        """Build from a typed event model (envelope + typed payload)."""
        event = cls(type=str(model.type), payload=dict(model.payload))
        event.ts = str(model.ts)
        return event

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "ts": self.ts, "payload": self.payload}


_TERMINAL_ABNORMAL = frozenset({"CANCELLED", "TIMED_OUT", "INTERRUPTED", "FAILED"})


def _terminal_reset_needed(status: str | None) -> bool:
    """D2/P0-D (I6): a terminal-abnormal invocation status must never be
    silently continued — the next invocation starts a fresh super-step."""
    return bool(status) and status in _TERMINAL_ABNORMAL


async def _cancellation_requested(redis: Any, session_id: str) -> bool:
    """FE Step 2: cooperative cancel flag (POST /sessions/{id}/cancel).

    Degrade-open: a Redis outage never cancels a run and never raises.
    """
    try:
        return bool(await redis.get(f"nexus:cancel:agent_run:{session_id}"))
    except Exception:
        return False


async def _clear_cancellation(redis: Any, session_id: str) -> None:
    """A fresh invocation must never inherit a stale cancel flag."""
    try:
        await redis.delete(f"nexus:cancel:agent_run:{session_id}")
    except Exception:
        pass


def build_contract_meta() -> dict[str, Any]:
    """P1-B.1: the current checkpoint compatibility contract.

    Architecture fingerprint + AgentState schema version. A checkpoint is
    only resumed under the exact contract it was created for.
    """
    try:
        from nexus.agent.architecture import ArchitectureVersion
        from nexus.agent.state_schema import AGENT_STATE_SCHEMA_VERSION

        return {
            "arch_fp": ArchitectureVersion.cache_fingerprint(),
            "state_schema": AGENT_STATE_SCHEMA_VERSION,
        }
    except Exception:
        return {"arch_fp": "", "state_schema": "unknown"}


def checkpoint_contract_ok(values: Any) -> str | None:
    """P1-B.1: None when the checkpoint may resume; a reason string when it
    must be refused. Missing metadata, architecture or state-schema
    mismatch → refuse safely (never reinterpret old state, never execute a
    stale graph)."""
    meta = values.get("_contract_meta") if isinstance(values, dict) else None
    if not isinstance(meta, dict) or not meta:
        return "missing checkpoint compatibility metadata"
    current = build_contract_meta()
    if meta.get("arch_fp") != current["arch_fp"]:
        return "architecture fingerprint mismatch"
    if meta.get("state_schema") != current["state_schema"]:
        return "state schema version mismatch"
    return None


def _append_step_progress(
    events: list[AgentEvent],
    step: str,
    status: str,
    text: str,
    tool_name: str,
) -> None:
    """Append a typed StepProgress event (the stable UI contract)."""
    from nexus.events.models import build_event

    events.append(AgentEvent.from_model(build_event("step_progress", {
        "step": step,
        "status": status,
        "text": text,
        "tool_name": tool_name,
    })))


def _emit_execution_completed(
    state: dict[str, Any],
    status: str,
    event_bus: Any,
    session_id: str,
    yield_event: bool = False,
) -> AgentEvent | None:
    """Emit the typed ExecutionCompletedEvent at run end (best-effort)."""
    try:
        from nexus.events.models import build_event

        duration = 0.0
        if state.get("_latency_estimate_ms"):
            duration = float(state["_latency_estimate_ms"])
        event = AgentEvent.from_model(build_event("execution_completed", {
            "status": status,
            "final_response": str(state.get("final_response", "") or ""),
            "cost_usd": float(state.get("total_cost_usd", 0.0) or 0.0),
            "duration_ms": duration,
        }))
        if event_bus is not None and not yield_event:
            import asyncio as _asyncio

            try:
                _asyncio.ensure_future(
                    event_bus.publish(agent_channel(session_id), event.to_dict())
                )
            except Exception:
                pass
        return event
    except Exception:
        return None


class AgentRunner:
    """Orchestrates a single agent run and streams events.

    Usage::

        runner = AgentRunner(llm_client, tool_executor, event_bus)
        async for event in runner.invoke(
            session_id=..., user_message=..., user_id=...
        ):
            print(event.to_dict())
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        tool_executor: ToolExecutor | None = None,
        event_bus: EventBus | None = None,
        session_factory: Any = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._executor = tool_executor
        self._event_bus = event_bus
        self._session_factory = session_factory
        self._checkpointer = checkpointer
        # Initialize GlobalContext singleton at startup (no-op if already set)
        if get_global_context().compiled_graph is None:
            set_global_context(get_global_context())

    async def _build_graph(self) -> Any:
        """Return the compiled graph, cached at module level.

        The graph is stateless — all run state lives in the checkpointer,
        so a single compiled instance can be safely reused across all
        invocations.  Rebuilding on every request adds 30-50ms overhead.
        """
        global _compiled_graph
        if _compiled_graph is None:
            async with _graph_lock:
                if _compiled_graph is None:
                    _compiled_graph = build_agent_graph(
                        llm_client=self._llm,
                        tool_executor=self._executor,
                        event_bus=self._event_bus,
                        session_factory=self._session_factory,
                        checkpointer=self._checkpointer,
                    )
        return _compiled_graph

    # ------------------------------------------------------------------
    # Lock helpers
    # ------------------------------------------------------------------

    async def _try_acquire_lock(
        self, redis: Any, lock_key: str, ttl_s: int
    ) -> tuple[str, bool]:
        """Try to acquire a distributed lock.

        Returns (lock_token, acquired). On Redis outage, degrades to
        (no-op token, True) so the agent still runs — the lock is an
        optimization, not a correctness gate.
        """
        lock_token = secrets.token_hex(16)
        try:
            acquired = await redis.set(lock_key, lock_token, nx=True, ex=ttl_s)
            return lock_token, bool(acquired)
        except Exception as exc:
            logger.warning("lock.acquire_redis_down", error=str(exc)[:200])
            return lock_token, True

    async def _renew_lock(self, redis: Any, key: str, token: str, ttl_s: int) -> None:
        """Background heartbeat: extend lock TTL every ttl/3 seconds.

        Cancelled by the caller when ``astream`` completes. Transient Redis
        errors are tolerated — the heartbeat simply retries on the next tick.
        """
        interval = max(1, ttl_s // 3)
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    renewed = await redis.eval(_RENEW_LUA, 1, key, token, str(ttl_s))
                except Exception as exc:
                    logger.warning("lock.renew_redis_error", error=str(exc)[:200])
                    continue
                if not renewed:
                    logger.warning("lock.renewal_failed", key=key, reason="stolen or expired")
                    break
        except asyncio.CancelledError:
            pass

    async def _release_lock(self, redis: Any, key: str, token: str) -> None:
        """Atomically release the lock if we still own it."""
        try:
            await redis.eval(_RELEASE_LUA, 1, key, token)
        except Exception:
            logger.warning("lock.release_failed", key=key)

    # ------------------------------------------------------------------
    # Invoke
    # ------------------------------------------------------------------

    async def invoke(
        self,
        session_id: uuid.UUID | str,
        user_message: str,
        config: dict[str, Any] | None = None,
        user_context: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the agent graph and yield events.

        Loads prior state from the checkpointer (multi-turn memory) and
        appends the new user message to the accumulated conversation history.

        Args:
            session_id: The conversation session ID.
            user_message: The user's latest message.
            config: Optional LangGraph ``RunnableConfig`` dict.
            user_context: Optional verified identity context
                (``{"user_id": ..., "roles": [...]}`` — C3/P0-C) consumed by
                the executor's authorization gate. Never trust client
                input; only the auth middleware may populate it.
            request_id: The API request correlation id (P2-B) — persisted
                with the invocation outcome so every answer is traceable
                to the HTTP request that produced it.

        Yields:
            ``AgentEvent`` instances as the graph progresses.
        """
        sid = str(session_id)
        _request_id = request_id

        graph = await self._build_graph()
        run_config: dict[str, Any] = dict(config or {})
        run_config.setdefault("configurable", {})["thread_id"] = sid

        # Build initial state — preserve messages from prior turns (multi-turn memory)
        # Try to load prior state from the checkpointer
        prior_messages: list[dict[str, Any]] = []
        prior_state: Any = None
        prior_status: str | None = None
        try:
            prior_state = await graph.aget_state(run_config)
            if prior_state is not None and prior_state.values:
                prior_status = prior_state.values.get("_invocation_status")
                # P1-B.1 CHECKPOINT COMPATIBILITY CONTRACT: a checkpoint is
                # only resumed under the EXACT contract it was created for.
                # Missing or mismatched compatibility metadata (architecture
                # fingerprint / state-schema version) → refuse safely: the
                # stale graph is NOT executed and the old state is NOT
                # reinterpreted — the invocation starts clean.
                _contract = checkpoint_contract_ok(prior_state.values)
                if _contract is not None:
                    logger.warning(
                        "runner.checkpoint_contract_refused",
                        session_id=sid,
                        reason=_contract,
                    )
                    try:
                        await graph.aupdate_state(
                            run_config,
                            {"messages": [], "_contract_meta": build_contract_meta()},
                            as_node="__start__",
                        )
                    except Exception as _contract_exc:
                        logger.warning(
                            "runner.checkpoint_contract_reset_failed",
                            session_id=sid,
                            error=str(_contract_exc)[:200],
                        )
                    prior_messages = []
                    prior_state = None
                    prior_status = None
                else:
                    prior_messages = list(prior_state.values.get("messages", []))
                # D2/P0-D (I6): a TERMINAL-abnormal checkpoint (crashed /
                # timed-out / interrupted / failed run) must never silently
                # continue the old graph. Reset the pending tasks so this
                # invocation starts a FRESH planning/execution super-step —
                # messages are preserved (the conversation continues).
                if _terminal_reset_needed(prior_status):
                    logger.info(
                        "runner.stale_graph_reset",
                        session_id=sid,
                        status=prior_status,
                    )
                    try:
                        await graph.aupdate_state(
                            run_config,
                            {"_invocation_status": "COMPLETED"},
                            as_node="__start__",
                        )
                    except Exception as _reset_exc:
                        logger.warning(
                            "runner.stale_graph_reset_failed",
                            session_id=sid,
                            error=str(_reset_exc)[:200],
                        )
                # Clear ephemeral fields from prior state — they belong to the previous turn
                for ef in _EPHEMERAL_FIELDS:
                    if ef in prior_state.values and ef not in prior_state.values.get("messages", []):
                        prior_state.values.pop(ef, None)
        except Exception:
            pass

        # Reset artifact graph between turns — UNLESS an interactive workflow is active,
        # so workflow steps can read the previous step's tool results across turns
        active_wf = (prior_state.values.get("_active_workflow_id") if prior_state and prior_state.values else None)
        if not active_wf:
            reset_artifact_graph(sid)

        # Tag first-ever user message as milestone (survives rolling window)
        user_msg: dict[str, Any] = {"role": "user", "content": user_message}
        is_first_turn = not prior_messages
        if is_first_turn:
            user_msg["_milestone"] = True

        _settings = get_settings()

        # Build SessionContext for this invocation
        session_ctx = SessionContext(
            session_id=sid,
        )

        initial_state: AgentState = {
            "messages": prior_messages + [user_msg],
            "session_id": sid,
            "gathered_requirements": prior_state.values.get("gathered_requirements", {}) if prior_state else {},
            "_tool_executed_in_turn": False,
            "iteration_count": 0,
            "tool_results": [],
            "final_response": None,
            "intent": None,
            "errors": [],
            "intent_analysis": None,
            "response_type": "tool",
            "reflection_feedback": "",
            "working_memory": prior_state.values.get("working_memory", {"entries": []}) if prior_state else {"entries": []},
            "total_cost_usd": 0.0,
            "_cost_breakdown": {},
            "_total_tokens": 0,
            "_routing_decision": "continue",
            "_safety_result": {"passed": True, "action": "allow", "reason": ""},
            "_query_type": "action",
            "_goals": ["action"],
            "_needs_requirements": False,
            "_force_query_type": "",
            "_preferred_tools": [],
            "_executor_failed": [],
            "_executor_all_success": True,
            "_tool_retry_counts": {},
            "_pending_tasks": [],
            "_approval_granted": False,
            "_approval_decision": None,
            "_needs_approval": False,
            # Approval chain state MUST be reset explicitly — it is an ephemeral
            # field that the checkpointer would otherwise restore from the last
            # checkpoint (LangGraph merges stored channel values). A completed
            # chain from a previous turn would auto-grant future approvals.
            "_approval_chain_state": None,
            "_pending_approval_tools": [],
            "_approval_requested_at": None,
            "_approval_pending": None,
            "_approval_checkpoint_context": None,
            "_approval_modification": None,
            # Ephemeral routing flag — MUST reset each turn. The modify branch
            # sets it True to bypass the workflow manager while replanning;
            # leaking it forward would skip the conversational checkpoint
            # routing on the next user message.
            "_bypass_workflow": False,
            # Routing flags MUST be explicitly reset: LangGraph merges the
            # checkpointed channel values under absent input keys, so a
            # workflow's ``_route_to_compiler``/``_route_to_planner`` from a
            # previous turn would otherwise re-route a NEW message into the
            # stale compiler path (observed: a new query re-executed the old
            # workflow instead of planning).
            "_route_to_compiler": False,
            "_route_to_planner": False,
            # Domain hint computed by the router each turn (capability
            # classification) — never carries across turns.
            "_domain_hint": None,
            # A3/P1-A: per-invocation identity for memory provenance.
            "_invocation_id": str(uuid.uuid4()),
            # P1-B.1: the checkpoint compatibility contract (arch fp +
            # state schema version) — stamped so every checkpoint records
            # the contract it was created under.
            "_contract_meta": build_contract_meta(),
        }

        # C3/P0-C: verified identity context (auth middleware only) —
        # consumed by the executor's authorization gate (allowed_roles).
        if user_context and isinstance(user_context, dict):
            initial_state["user_context"] = dict(user_context)

        # Preserve an OPEN conversational approval checkpoint across turns —
        # it must survive until the user decides in-chat. The resume node
        # clears it once the decision is consumed.
        if prior_state is not None and prior_state.values:
            for _cp_key in ("_approval_pending", "_approval_checkpoint_context", "_approval_modification"):
                if prior_state.values.get(_cp_key) is not None:
                    initial_state[_cp_key] = _deepcopy(prior_state.values[_cp_key])

        # Preserve interactive workflow context across every invoke boundary.
        # Any `_workflow_*` key (or `_active_workflow_id`) present in the prior
        # checkpoint is carried forward explicitly — LangGraph merges declared
        # channels, but this guarantees the state machine never loses its
        # place between turns (e.g. after an approval resume or a re-invoke).
        # DEEPCOPY: checkpoint values are shared references — carrying them by
        # reference lets a later in-place write mutate a prior checkpoint object.
        if prior_state is not None and prior_state.values:
            for _wf_key in list(prior_state.values.keys()):
                if _wf_key == "_active_workflow_id" or _wf_key.startswith("_workflow_"):
                    if _wf_key not in _EPHEMERAL_FIELDS:
                        initial_state[_wf_key] = _deepcopy(prior_state.values[_wf_key])

        redis = get_redis_client()
        lock_acquired = False
        lock_key = f"lock:agent_run:{sid}"
        lock_token = ""
        heartbeat_task: asyncio.Task[None] | None = None

        if redis is not None:
            ttl = _settings.agent.run_lock_ttl_s
            lock_token, lock_acquired = await self._try_acquire_lock(redis, lock_key, ttl)
            if not lock_acquired:
                error_event = AgentEvent(
                    "error",
                    {"message": "Another agent run is already in progress for this session"},
                )
                yield error_event
                return
            heartbeat_task = asyncio.ensure_future(
                self._renew_lock(redis, lock_key, lock_token, ttl)
            )

        _tracer = get_tracer()
        _start_ts = time_module.perf_counter()
        _last_state: dict[str, Any] = {}
        _error_msg: str | None = None

        # REASONING BUDGET (P0): the per-invocation contract — every
        # subsystem (validator/compiler/recovery/executor) draws from this
        # ONE budget. The runner enforces the wall-time + graph-step
        # dimensions; the nodes enforce the replan/recovery/tool dimensions.
        try:
            from nexus.agent.budget import ReasoningBudget

            _budget = ReasoningBudget(
                max_wall_time_ms=float(_settings.agent.max_invocation_wall_time_ms),
                max_graph_steps=int(_settings.agent.max_graph_steps),
                max_replans=int(_settings.agent.max_replans),
                max_recovery_attempts=int(_settings.agent.max_recovery_attempts),
                max_llm_calls=int(_settings.agent.max_llm_calls),
                max_tool_calls=int(_settings.agent.max_tool_calls),
                max_cost_usd=float(_settings.agent.max_invocation_cost_usd),
            )
            initial_state["_invocation_budget"] = _budget.to_dict()
        except Exception:
            _budget = None

        span = _tracer.start_span("agent.invoke")
        span.set_attribute("session_id", sid)
        span.set_attribute("model", _settings.llm.default_model)

        try:
            _node_start_times: dict[str, float] = {}
            _last_event_time: float = time_module.perf_counter()
            initial_state.setdefault("_invocation_status", "RUNNING")
            # FE Step 2: a fresh invocation never inherits a stale cancel flag.
            if redis is not None:
                await _clear_cancellation(redis, sid)
            async for event in graph.astream(initial_state, run_config, stream_mode="updates"):
                if not isinstance(event, dict):
                    logger.warning("runner.skipping_non_dict_event", event_type=type(event).__name__, event=repr(event)[:200])
                    continue
                if _budget is not None:
                    # A1/P1-A: merge the state carrier (nodes write their
                    # ledger back) so the runner's wall-clock/steps checks
                    # see llm/tool/cost consumption from every subsystem.
                    try:
                        _budget.merge(_last_state.get("_invocation_budget"))
                    except Exception:
                        pass
                    _budget.consume("graph_steps")
                    _exceeded = _budget.exceeded()
                    if _exceeded:
                        logger.error(
                            "runner.invocation_budget_exceeded",
                            dimension=_exceeded,
                            consumed=_budget.consumed,
                        )
                        initial_state["_invocation_status"] = (
                            "TIMED_OUT" if _exceeded == "wall_time" else "INTERRUPTED"
                        )
                        # PH-1 (I16): the terminal marker must land in the
                        # PERSISTED state, not just the seed — finalization
                        # reads _last_state, and the checkpoint must never
                        # be overwritten back to COMPLETED.
                        _last_state["_invocation_status"] = (
                            "TIMED_OUT" if _exceeded == "wall_time" else "INTERRUPTED"
                        )
                        yield AgentEvent(
                            "error",
                            {"message": f"invocation budget exceeded ({_exceeded})"},
                        )
                        _error_msg = f"invocation budget exceeded ({_exceeded})"
                        break
                # FE Step 2 cooperative cancellation: an operator (SSE client
                # Stop, WS cancel) sets nexus:cancel:agent_run:{sid}; the run
                # checks it between node events and cancels itself — the
                # observer is disposable, the cancel is durable.
                if redis is not None:
                    _cancel_requested = await _cancellation_requested(redis, sid)
                    if _cancel_requested:
                        logger.info("runner.cancel_requested", session_id=sid)
                        raise asyncio.CancelledError
                node_name: str = next(iter(event))
                state_update: Any = event[node_name]

                # Track per-node timing: the inter-event delta attributes each
                # node's wall time to the node that just completed (single
                # visits included). Repeated visits accumulate.
                now = time_module.perf_counter()
                _node_duration = int((now - _last_event_time) * 1000)
                _last_event_time = now
                _node_start_times[node_name] = now

                # Per-stage metrics accumulator (observability): node → ms.
                # Surfaced in the final state under ``_stage_metrics`` so
                # latency attribution is data, not guessing.
                _stage_metrics = dict(_last_state.get("_stage_metrics") or {})
                _stage_metrics[node_name] = int(_stage_metrics.get(node_name, 0) or 0) + _node_duration
                _last_state["_stage_metrics"] = _stage_metrics

                # Per-node OpenTelemetry span: node, duration, cache/token
                # attributes when present. Failures must never break the run.
                if _NODE_TRACER is not None:
                    _span = _NODE_TRACER.start_span(
                        f"agent.node.{node_name}",
                        attributes={
                            "agent.node": node_name,
                            "agent.node.duration_ms": _node_duration,
                            "agent.session_id": sid,
                        },
                    )
                    try:
                        if isinstance(state_update, dict):
                            _span.set_attribute(
                                "agent.node.cached",
                                bool(state_update.get("cached")),
                            )
                            _span.set_attribute(
                                "agent.node.tokens",
                                int(state_update.get("_total_tokens", 0) or 0),
                            )
                    finally:
                        _span.end()

                if not isinstance(state_update, dict):
                    logger.debug("runner.non_dict_update", node=node_name, value_type=type(state_update).__name__)
                    state_update = {node_name: state_update}
                    _last_state.update(state_update)
                    agent_events = self._translate(node_name, state_update)
                else:
                    _last_state.update(state_update)
                    agent_events = self._translate(node_name, state_update)

                # Emit node lifecycle events for observability (typed model:
                # cost/retries/decision-reason fields, validated).
                from nexus.events.models import build_event

                node_event = AgentEvent.from_model(build_event("node_completed", {
                    "node": node_name,
                    "duration_ms": _node_duration,
                    "has_output": bool(state_update),
                    "cost_usd": float(state_update.get("_cost_estimate", 0.0) or 0.0)
                    if node_name == "EstimatorNode" else 0.0,
                    "retries": int(state_update.get("_plan_validator_rounds", 0) or 0)
                    if node_name == "PlanValidatorNode" else 0,
                }))
                if self._event_bus:
                    # Redis outage must NOT fail a successful agent run —
                    # telemetry is best-effort.
                    try:
                        await self._event_bus.publish(agent_channel(sid), node_event.to_dict())
                    except Exception as _pub_exc:
                        logger.warning("runner.event_publish_failed", error=str(_pub_exc)[:200])
                yield node_event

                for agent_event in agent_events:
                    if self._event_bus:
                        try:
                            await self._event_bus.publish(
                                agent_channel(sid),
                                agent_event.to_dict(),
                            )
                        except Exception as _pub_exc:
                            logger.warning("runner.event_publish_failed", error=str(_pub_exc)[:200])
                    yield agent_event

        except asyncio.CancelledError:
            logger.info("agent.run.cancelled", session_id=sid)
            _emit_execution_completed(_last_state, "cancelled", self._event_bus, sid)
        except Exception as exc:
            _error_msg = str(exc)
            logger.error("agent.run.failed", exc_info=exc)
            error_event = AgentEvent("error", {"message": _error_msg})
            if self._event_bus:
                try:
                    await self._event_bus.publish(agent_channel(sid), error_event.to_dict())
                except Exception as _pub_exc:
                    logger.warning("runner.event_publish_failed", error=str(_pub_exc)[:200])
            yield error_event
            _emit_execution_completed(_last_state, "failed", self._event_bus, sid)
        else:
            # Normal completion: final status from the last state.
            # Terminal-abnormal markers (TIMED_OUT/INTERRUPTED — PH-1) are
            # monotonic: once set, they are never downgraded to COMPLETED.
            _terminal = _last_state.get("_invocation_status")
            final_status = "completed"
            if _terminal in _TERMINAL_ABNORMAL:
                final_status = _terminal.lower()
            elif _last_state.get("_executor_failed"):
                final_status = "failed"
            elif _last_state.get("_background_task_id"):
                final_status = "queued"
            try:
                if _terminal in (None, "RUNNING"):
                    _last_state["_invocation_status"] = "COMPLETED"
                    # D2/P0-D (I6): persist the terminal marker so the
                    # checkpoint never reports a finished run as running.
                    await graph.aupdate_state(
                        run_config,
                        {"_invocation_status": "COMPLETED"},
                    )
                else:
                    # Terminal-abnormal (budget-exceeded): persist the truth
                    # NOW — the finally block also resets the pending graph
                    # (as_node="__start__"), so a crash between here and the
                    # finally can never leave a misleading COMPLETED.
                    await graph.aupdate_state(
                        run_config,
                        {"_invocation_status": _terminal},
                    )
            except Exception:
                pass
            yield _emit_execution_completed(_last_state, final_status, self._event_bus, sid, yield_event=True)
        finally:
            span.end()
            # CANCELLATION (P0): the async-generator close (client
            # disconnect) or an exception cancels the invocation — record
            # the terminal state so interrupted runs are attributable,
            # never silent.
            try:
                _target = _last_state if _last_state else initial_state
                if _target.get("_invocation_status") in (None, "RUNNING"):
                    _target["_invocation_status"] = "CANCELLED"
            except Exception:
                pass
            # D2/P0-D (I6): persist the TERMINAL-ABNORMAL marker into the
            # checkpoint (crash/timeout/interrupt/failure) and clear the
            # pending graph — the next invocation must start fresh, never
            # silently resume the stale plan.
            try:
                _terminal = _target.get("_invocation_status") or ""
                if _terminal_reset_needed(_terminal):
                    await graph.aupdate_state(
                        run_config,
                        {"_invocation_status": _terminal},
                        as_node="__start__",
                    )
            except Exception:
                pass
            # Persist outcome record (fire-and-forget)
            latency = int((time_module.perf_counter() - _start_ts) * 1000)
            try:
                outcome = InvocationOutcome.from_state(
                    _last_state, latency, error_message=_error_msg,
                    request_id=_request_id,
                )
                # Fire and forget — tracked to prevent GC dropping the task
                _track_bg_task(asyncio.ensure_future(persist_outcome(outcome)))
            except Exception:
                pass
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
            if lock_acquired and redis is not None:
                await self._release_lock(redis, lock_key, lock_token)


    # ------------------------------------------------------------------
    # Recover from checkpoint
    # ------------------------------------------------------------------

    async def recover(
        self,
        session_id: str,
        target_node: str | None = None,
    ) -> dict[str, Any]:
        """Recover the graph to the most recent checkpoint.

        Queries the checkpointer's state history to find the checkpoint
        before ``target_node`` was about to execute. If no target_node
        is specified, finds the latest checkpoint before the graph ended.

        Restores the graph state to that checkpoint and returns the
        recovered messages + state for re-invocation.

        Args:
            session_id: The conversation session ID.
            target_node: Node name to recover to (e.g. ``"PlannerNode"``,
                ``"ExecutorNode"``). If None, recovers to the penultimate
                checkpoint (the one before the graph ended).

        Returns:
            Dict with ``state`` (the recovered state values) and
            ``checkpoint`` (the checkpoint tuple). Empty dict if no
            suitable checkpoint found.

        Raises:
            ValueError: If no checkpoints exist for this session.
        """
        sid = str(session_id)
        graph = await self._build_graph()
        config = {"configurable": {"thread_id": sid}}

        # Get latest state first to verify the session exists
        latest = await graph.aget_state(config)
        if latest is None or not latest.values:
            logger.warning("recover.no_session", session_id=sid)
            return {}

        from nexus.agent.checkpoint_manager import (
            find_checkpoint_before,
            find_latest_checkpoint,
        )

        if target_node:
            target = await find_checkpoint_before(graph, config, target_node)
            if target is None:
                logger.warning("recover.target_not_found", session_id=sid, target=target_node)
                return {}
        else:
            target = await find_latest_checkpoint(graph, config)
            if target is None:
                logger.warning("recover.no_history", session_id=sid)
                return {}

        # Get checkpoint ID from the snapshot's config
        target_config = target.config if hasattr(target, "config") else None
        if target_config is None:
            logger.warning("recover.no_config", session_id=sid)
            return {}

        target_cp_id = target_config.get("configurable", {}).get("checkpoint_id") if isinstance(target_config, dict) else None
        if target_cp_id is None:
            logger.warning("recover.no_checkpoint_id", session_id=sid)
            return {}

        # Restore to the target checkpoint
        config_with_checkpoint = {
            "configurable": {
                "thread_id": sid,
                "checkpoint_id": target_cp_id,
            },
        }
        recovered = await graph.aget_state(config_with_checkpoint)

        if recovered is None or not recovered.values:
            logger.warning("recover.restore_failed", session_id=sid)
            return {}

        rec_values = recovered.values
        logger.info(
            "recover.restored",
            session_id=sid,
            target=target_node or "last",
            checkpoint_id=str(target_cp_id)[:12],
            message_count=len(rec_values.get("messages", [])),
        )

        return {
            "state": dict(rec_values),
            "checkpoint": target_cp_id,
        }

    # ------------------------------------------------------------------
    # Resume
    # ------------------------------------------------------------------

    async def resume(
        self,
        session_id: str,
        resume_value: dict[str, Any],
    ) -> AsyncIterator[AgentEvent]:
        """Resume an interrupted agent run and yield events.

        Builds a fresh graph, checks the checkpointer for a paused state,
        then streams the resume with its own lock + heartbeat.

        Args:
            session_id: The conversation session ID (thread_id).
            resume_value: The LangGraph ``Command(resume=...)`` payload.

        Yields:
            ``AgentEvent`` instances as the graph resumes.
        """
        graph = await self._build_graph()
        config = {"configurable": {"thread_id": session_id}}

        snapshot = await graph.aget_state(config)
        if not snapshot.next:
            yield AgentEvent("error", {"message": "No paused run to resume"})
            return

        redis = get_redis_client()
        lock_acquired = False
        lock_key = f"lock:agent_run:{session_id}"
        lock_token = ""
        heartbeat_task: asyncio.Task[None] | None = None

        if redis is not None:
            ttl = get_settings().agent.run_lock_ttl_s
            lock_token, lock_acquired = await self._try_acquire_lock(redis, lock_key, ttl)
            if not lock_acquired:
                yield AgentEvent(
                    "error",
                    {"message": "Another agent run is already in progress for this session"},
                )
                return
            heartbeat_task = asyncio.ensure_future(
                self._renew_lock(redis, lock_key, lock_token, ttl)
            )

        try:
            async for event in graph.astream(
                Command(resume=resume_value),
                config,
                stream_mode="updates",
            ):
                node_name: str = next(iter(event))
                state_update: dict[str, Any] = event[node_name]

                for agent_event in self._translate(node_name, state_update):
                    if self._event_bus:
                        await self._event_bus.publish(
                            agent_channel(session_id),
                            agent_event.to_dict(),
                        )
                    yield agent_event
        except asyncio.CancelledError:
            logger.info("agent.resume.cancelled", session_id=session_id)
        except Exception as exc:
            logger.error("agent.resume.failed", session_id=session_id, exc_info=exc)
            error_event = AgentEvent("error", {"message": str(exc)})
            if self._event_bus:
                await self._event_bus.publish(agent_channel(session_id), error_event.to_dict())
            yield error_event
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
            if lock_acquired and redis is not None:
                await self._release_lock(redis, lock_key, lock_token)

    # ------------------------------------------------------------------
    # Event translation
    # ------------------------------------------------------------------

    @staticmethod
    def _translate(node_name: str, state_update: Any) -> list[AgentEvent]:
        """Map a LangGraph state update to zero or more ``AgentEvent`` instances.

        ``state_update`` is normally a dict but may be a list from an Annotated
        reducer (e.g. messages).  In that case we skip event emission.
        """
        events: list[AgentEvent] = []

        if not isinstance(state_update, dict):
            return events

        # Extract inner node name (handles subgraph namespacing if any)
        inner = node_name.split(":")[-1] if ":" in node_name else node_name

        # --- ResponseNode → final answer ---
        fr = state_update.get("final_response")
        if fr is not None and inner == "ResponseNode":
            from nexus.events.models import build_event

            events.append(AgentEvent.from_model(build_event("final_response", {
                "text": str(fr),
                "cost_usd": float(state_update.get("total_cost_usd", 0.0) or 0.0),
                "latency_ms": float(state_update.get("_latency_estimate_ms", 0.0) or 0.0),
                # P1-B: the explicit terminal status — the benchmark can
                # distinguish SUCCESS / PARTIAL_SUCCESS / EXECUTION_FAILED /
                # PLANNING_FAILED instead of inferring from prose.
                "response_status": str(state_update.get("_response_status", "") or ""),
                # D10: synthesis-coverage breakdown — evidence/entities
                # required vs rendered (generation-reliability split).
                "coverage_breakdown": state_update.get("_response_coverage_breakdown") or {},
            })))

        # --- KnowledgeAssistantNode → knowledge response ---
        if fr is not None and inner == "KnowledgeAssistantNode":
            from nexus.events.models import build_event

            events.append(AgentEvent.from_model(build_event("final_response", {
                "text": str(fr),
            })))

        # --- RequirementCollectorNode → clarification question (the
        # collector's question IS the turn's final answer — without this
        # event the API response comes back empty) ---
        if fr is not None and inner == "RequirementCollectorNode":
            from nexus.events.models import build_event

            events.append(AgentEvent.from_model(build_event("final_response", {
                "text": str(fr),
                "response_type": "clarification",
            })))

        # --- RequirementCollectorNode → clarification question ---
        if inner == "RequirementCollectorNode":
            asked = state_update.get("_clarification_asked")
            if asked and isinstance(asked, dict):
                events.append(AgentEvent("clarification_question", {
                    "question": asked.get("question", ""),
                    "slots_filled": len(state_update.get("_clarification_slots", {})),
                }))

        # --- RouterNode → intent_extracted + query classification ---
        # NOTE: single branch — an ``elif`` with the same condition would be
        # dead code (the first ``if`` always matches RouterNode).
        if inner == "RouterNode":
            intent = state_update.get("intent")
            if intent:
                events.append(AgentEvent("intent_extracted", {
                    "query_type": intent.get("query_type", ""),
                    "confidence": intent.get("confidence", 0.0),
                    "suggested_capability": intent.get("suggested_capability"),
                }))
            qtype = state_update.get("_query_type", "")
            if qtype:
                preferred = state_update.get("_preferred_tools", [])
                events.append(AgentEvent(
                    "tool_selected",
                    {
                        "intent": qtype,
                        "parameters": {"query_type": qtype, "preferred_tools": preferred},
                    },
                ))
                # Decision event — answers WHY (goals + domain + requirements).
                from nexus.events.models import build_event

                events.append(AgentEvent.from_model(build_event("routing_decision", {
                    "decision": qtype,
                    "reason": "goals: " + ", ".join(state_update.get("_goals", []) or []),
                    "candidates": preferred,
                })))

        # --- PlanValidatorNode → deterministic decision ---
        elif inner == "PlanValidatorNode":
            action = state_update.get("_plan_validator_action", "")
            if action:
                from nexus.events.models import build_event

                events.append(AgentEvent.from_model(build_event("routing_decision", {
                    "decision": f"plan_validator:{action}",
                    "reason": "; ".join(state_update.get("_plan_validator_errors", []) or []),
                })))

        # --- SemanticPlannerNode → map degradation (PH-5: a stripped
        # fan-out is never invisible) + planning telemetry (PH-6A:
        # latency / chunk timing / resolution suppressions) ---
        elif inner == "SemanticPlannerNode":
            deg = state_update.get("_map_degradations")
            if deg:
                events.append(AgentEvent("map_degraded", {
                    "degradations": deg,
                }))
            supp = state_update.get("_resolution_suppressions")
            if supp:
                events.append(AgentEvent("resolution_suppressed", {
                    "suppressions": supp,
                }))
            chunk = state_update.get("_planner_chunk_timing")
            latency = state_update.get("_planner_latency_ms")
            if chunk or latency:
                events.append(AgentEvent("planner_timing", {
                    "latency_ms": latency or 0,
                    "chunk_timing": chunk or {},
                }))

        # --- CompilerNode → execution graph compiled + composition progress ---
        elif inner == "CompilerNode":
            graph = state_update.get("_execution_graph")
            if graph and isinstance(graph, dict):
                waves = graph.get("waves", [])
                # plan_created step names (F1/P0-B): ToolNodes expose
                # capability/tool_name at the top level; MapNodes nest the
                # body ToolNode — unwrap it so the event never falls back
                # to a bare node-id hash.
                node_summary: dict[str, str] = {}
                for k, v in (graph.get("nodes", {}) or {}).items():
                    if not isinstance(v, dict):
                        continue
                    name = str(v.get("capability") or v.get("tool_name") or "")
                    if not name and isinstance(v.get("body"), dict):
                        name = str(
                            v.get("body").get("tool_name")
                            or v.get("body").get("capability")
                            or ""
                        )
                    node_summary[k] = name or k
                from nexus.events.models import build_event

                events.append(AgentEvent.from_model(build_event("plan_created", {
                    "steps": node_summary,
                    "waves": len(waves),
                    "strategy": state_update.get("_execution_strategy", ""),
                    "estimated_cost_usd": float(state_update.get("_cost_estimate", 0.0) or 0.0),
                    "estimated_latency_ms": int(state_update.get("_latency_estimate_ms", 0) or 0),
                })))
                # Step progress: QUEUED per planned step (stable UI contract).
                for _task_id, _tool in node_summary.items():
                    _append_step_progress(events, _task_id, "queued", f"Waiting: {_tool}", str(_tool))
            events.append(AgentEvent("workflow_composing_progress", {
                "phase": "compile",
                "status": "complete",
            }))

        # --- ExecutorNode → tool call results ---
        elif inner == "ExecutorNode":
            tool_results = state_update.get("tool_results", [])
            if tool_results:
                from nexus.events.models import build_event

                for tr in tool_results:
                    etype = "tool_call_completed" if tr.get("status") == "success" else "error"
                    # C4/P0-C: tool payloads are redacted before they reach
                    # the SSE stream — sensitive fields never leave the
                    # server in events.
                    from nexus.tools.sandbox import mask_sensitive_fields

                    _tr_data = tr.get("data")
                    if isinstance(_tr_data, dict):
                        _tr_data = mask_sensitive_fields(_tr_data)
                    events.append(AgentEvent.from_model(build_event(etype, {
                        "tool_name": tr.get("tool_name"),
                        "status": tr.get("status"),
                        "data": _tr_data,
                        "error": tr.get("error"),
                        "task_id": tr.get("task_id", ""),
                        "duration_ms": float(tr.get("duration_ms", 0.0) or 0.0),
                        "retries": int(tr.get("retries", 0) or 0),
                        "cached": bool(tr.get("cached", False)),
                    })))
                    # Step progress: terminal state per tool (UI contract).
                    _status = str(tr.get("status", "failed"))
                    if _status == "success":
                        _append_step_progress(
                            events, tr.get("task_id", ""), "completed",
                            f"Done: {tr.get('tool_name')}", str(tr.get("tool_name", "")),
                        )
                    elif _status == "skipped":
                        _append_step_progress(
                            events, tr.get("task_id", ""), "skipped",
                            f"Skipped: {tr.get('tool_name')}", str(tr.get("tool_name", "")),
                        )
                    else:
                        _append_step_progress(
                            events, tr.get("task_id", ""), "failed",
                            f"Failed: {tr.get('tool_name')}", str(tr.get("tool_name", "")),
                        )

        # --- OptimizerNode → composition progress ---
        elif inner == "OptimizerNode":
            snapshots = state_update.get("_optimization_snapshots", [])
            events.append(AgentEvent("workflow_composing_progress", {
                "phase": "optimize",
                "status": "complete",
                "snapshots": len(snapshots),
            }))

        # --- EstimatorNode → composition progress ---
        elif inner == "EstimatorNode":
            events.append(AgentEvent("workflow_composing_progress", {
                "phase": "estimate",
                "status": "complete",
                "within_budget": state_update.get("_within_budget", True),
                "strategy": state_update.get("_execution_strategy", ""),
                "estimated_cost_usd": float(state_update.get("_cost_estimate", 0.0) or 0.0),
                "estimated_latency_ms": int(state_update.get("_latency_estimate_ms", 0) or 0),
                "background": bool(state_update.get("_background_execution", False)),
            }))

        # --- ValidatorNode → validation progress ---
        elif inner == "ValidatorNode":
            validation_results = state_update.get("_validation_results", [])
            events.append(AgentEvent("validation_progress", {
                "total_checked": len(validation_results),
                "failures": [{"tier": f.get("tier"), "reason": f.get("reason", "")[:80]}
                             for f in validation_results if isinstance(f, dict)],
            }))

        # --- AggregatorNode → artifact produced ---
        elif inner == "AggregatorNode":
            results = state_update.get("_aggregated_results", {})
            if results and isinstance(results, dict) and any(results.values()):
                events.append(AgentEvent("artifact_produced", {
                    "aggregated_keys": list(results.keys())[:10],
                    "count": len(results),
                }))

        # --- ReflectionNode → retry or finalize ---
        elif inner == "ReflectionNode":
            decision = state_update.get("_routing_decision", "")
            if decision == "retry":
                events.append(AgentEvent("reflection_result", {
                    "score": 0.0,
                    "feedback": "Retrying failed tasks",
                    "reflection_count": 1,
                }))
                for _failed in (state_update.get("_executor_failed", []) or []):
                    _append_step_progress(
                        events, str(_failed), "retrying",
                        f"Retrying: {_failed}", str(_failed),
                    )

        # --- InteractiveWorkflowNode → workflow state transitions ---
        elif inner == "InteractiveWorkflowNode":
            wf_id = state_update.get("_active_workflow_id", "")

            if state_update.get("_route_to_compiler"):
                completed_steps = state_update.get("_workflow_completed_steps", [])
                events.append(AgentEvent("workflow_step_started", {
                    "workflow_id": wf_id,
                    "next_step": len(completed_steps),
                }))
            elif state_update.get("response_type") == "clarification":
                events.append(AgentEvent("workflow_input_required", {
                    "workflow_id": wf_id,
                    "question": state_update.get("final_response", ""),
                }))
            elif state_update.get("_bypass_workflow"):
                events.append(AgentEvent("workflow_paused", {
                    "workflow_id": wf_id,
                    "reason": "off_topic_query",
                }))
            elif state_update.get("response_type") == "cancellation":
                events.append(AgentEvent("workflow_cancelled", {
                    "workflow_id": wf_id,
                    "message": state_update.get("final_response", "Workflow cancelled."),
                }))
            elif state_update.get("_structured_payload"):
                events.append(AgentEvent("workflow_completed", {
                    "workflow_id": wf_id,
                    "payload": state_update.get("_structured_payload"),
                }))

        # ── Approval checkpoint (conversational, any node) ──────────
        # The user decides IN-CHAT: approve/reject/cancel/clarify/modify.
        # Only the GATE's own update is a pause request — other nodes echo
        # _approval_pending via the @context_node snapshot surfacing, which
        # must not re-emit. The resume node clears it to None.
        if inner == "ApprovalGateNode" and state_update.get("_approval_pending"):
            pending = state_update.get("_approval_pending")
            if isinstance(pending, dict):
                events.append(AgentEvent("approval_checkpoint", {
                    "message": state_update.get("final_response")
                        or pending.get("message", "Approval required"),
                    "tools": pending.get("tools", []),
                    "policy": pending.get("policy", ""),
                    "context": state_update.get("_approval_checkpoint_context", ""),
                    "options": ["approve", "reject", "cancel", "modify", "clarify"],
                }))
                for _tool in (pending.get("tools", []) or []):
                    _append_step_progress(
                        events, str(_tool), "approval",
                        f"Awaiting approval: {_tool}", str(_tool),
                    )

        # ── Errors (any node) ─────────────────────────────────────
        # UNIFIED SHAPE: always {"message": ...} — every other error event in
        # the runner uses this shape; clients must not special-case variants.
        errors = state_update.get("errors", [])
        if errors and isinstance(errors, list):
            last_error = errors[-1]
            events.append(AgentEvent("error", {
                "message": str(last_error)[:500] if last_error else "Unknown error",
            }))

        return events
