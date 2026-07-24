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
from datetime import UTC, datetime
from typing import Any

import time as time_module

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from nexus.agent.graph import build_agent_graph
from nexus.agent.state import AgentState, _EPHEMERAL_FIELDS
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient
from nexus.observability.outcomes import InvocationOutcome, persist_outcome
from nexus.observability.tracing import get_tracer
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.pubsub import EventBus, agent_channel
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor

logger = structlog.get_logger("nexus.agent.runner")

AGENT_EVENT_TYPES = frozenset(
    {
        "plan_created",
        "tool_selected",
        "tool_call_started",
        "tool_call_completed",
        "clarification_needed",
        "approval_required",
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


# Module-level cache for available tools (avoids DB query per request)
_tool_cache: list[dict[str, Any]] = []
_tool_cache_ts: float = 0
_TOOL_CACHE_TTL: int = 60


def _get_cached_tools() -> list[dict[str, Any]]:
    global _tool_cache, _tool_cache_ts
    import time as _time
    if _tool_cache and (_time.time() - _tool_cache_ts) < _TOOL_CACHE_TTL:
        return _tool_cache
    return []


async def _refresh_tool_cache(
    selector: DynamicToolSelector | None,
    session_factory: Callable[[], Any] | None,
) -> list[dict[str, Any]]:
    global _tool_cache, _tool_cache_ts
    import time as _time
    if selector is not None and session_factory is not None:
        try:
            from nexus.tools.schemas import ToolList  # noqa: PLC0415
            async with session_factory() as session:
                tl: ToolList = await selector._registry.list(session, page_size=1000)
                _tool_cache = [
                    {k: v for k, v in t.model_dump(mode="json").items() if k != "embedding"}
                    for t in tl.items
                ]
                _tool_cache_ts = _time.time()
        except Exception:
            logger.warning("runner.available_tools_prepopulate_failed")
    return _tool_cache


class AgentEvent:
    """An event emitted during agent execution.

    Attributes:
        type: One of the ``AGENT_EVENT_TYPES``.
        payload: Event-specific data.
        ts: ISO-8601 timestamp of the event.
    """

    def __init__(self, type: str, payload: dict[str, Any]) -> None:  # noqa: A002
        self.type = type
        self.payload = payload
        self.ts = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "ts": self.ts, "payload": self.payload}


class AgentRunner:
    """Orchestrates a single agent run and streams events.

    Usage::

        runner = AgentRunner(llm_client, tool_selector, tool_executor, event_bus)
        async for event in runner.invoke(
            session_id=..., user_message=..., user_id=...
        ):
            print(event.to_dict())
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        tool_selector: DynamicToolSelector | None = None,
        tool_executor: ToolExecutor | None = None,
        event_bus: EventBus | None = None,
        session_factory: Any = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._selector = tool_selector
        self._executor = tool_executor
        self._event_bus = event_bus
        self._session_factory = session_factory
        self._checkpointer = checkpointer

    def _build_graph(self) -> Any:
        """Build a fresh compiled graph (stateless — all state in checkpointer)."""
        return build_agent_graph(
            llm_client=self._llm,
            tool_selector=self._selector,
            tool_executor=self._executor,
            event_bus=self._event_bus,
            session_factory=self._session_factory,
            checkpointer=self._checkpointer,
        )

    # ------------------------------------------------------------------
    # Lock helpers
    # ------------------------------------------------------------------

    async def _try_acquire_lock(
        self, redis: Any, lock_key: str, ttl_s: int
    ) -> tuple[str, bool]:
        """Try to acquire a distributed lock.

        Returns (lock_token, acquired).
        """
        lock_token = secrets.token_hex(16)
        acquired = await redis.set(lock_key, lock_token, nx=True, ex=ttl_s)
        return lock_token, bool(acquired)

    async def _renew_lock(self, redis: Any, key: str, token: str, ttl_s: int) -> None:
        """Background heartbeat: extend lock TTL every ttl/3 seconds.

        Cancelled by the caller when ``astream`` completes.
        """
        interval = max(1, ttl_s // 3)
        try:
            while True:
                await asyncio.sleep(interval)
                renewed = await redis.eval(_RENEW_LUA, 1, key, token, str(ttl_s))
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
    ) -> AsyncIterator[AgentEvent]:
        """Run the agent graph and yield events.

        Loads prior state from the checkpointer (multi-turn memory) and
        appends the new user message to the accumulated conversation history.

        Args:
            session_id: The conversation session ID.
            user_message: The user's latest message.
            config: Optional LangGraph ``RunnableConfig`` dict.

        Yields:
            ``AgentEvent`` instances as the graph progresses.
        """
        sid = str(session_id)

        graph = self._build_graph()
        run_config: dict[str, Any] = dict(config or {})
        run_config.setdefault("configurable", {})["thread_id"] = sid

        # Build initial state — preserve messages from prior turns (multi-turn memory)
        # Try to load prior state from the checkpointer
        prior_messages: list[dict[str, Any]] = []
        try:
            prior_state = await graph.aget_state(run_config)
            if prior_state is not None and prior_state.values:
                prior_messages = list(prior_state.values.get("messages", []))
                # Clear ephemeral fields from prior state — they belong to the previous turn
                for ef in _EPHEMERAL_FIELDS:
                    if ef in prior_state.values and ef not in prior_state.values.get("messages", []):
                        prior_state.values.pop(ef, None)
        except Exception:
            pass

        # Tag first-ever user message as milestone (survives rolling window)
        user_msg: dict[str, Any] = {"role": "user", "content": user_message}
        is_first_turn = not prior_messages
        if is_first_turn:
            user_msg["_milestone"] = True

        _settings = get_settings()

        # Pre-populate available_tools (cache with 60s TTL — avoid DB query per request)
        available_tools = _get_cached_tools()
        if not available_tools and self._selector is not None and self._session_factory is not None:
            available_tools = await _refresh_tool_cache(self._selector, self._session_factory)

        initial_state: AgentState = {
            "messages": prior_messages + [user_msg],
            "session_id": sid,
            "_model": _settings.llm.default_model,
            "user_context": {},
            "plan": None,
            "current_step_index": 0,
            "gathered_requirements": prior_state.values.get("gathered_requirements", {}) if prior_state else {},
            "available_tools": available_tools,
            "_tool_executed_in_turn": False,
            "pending_approval": None,
            "iteration_count": 0,
            "scratchpad": "",
            "tool_results": [],
            "final_response": None,
            "intent": None,
            "missing_info_slots": None,
            "errors": [],
            "_bound_tools": [],
            "intent_analysis": None,
            "analysis_result": None,
            "needs_human_review": False,
            "questions_asked": 0,
            "response_type": "tool",
            "reflection_score": 0.0,
            "reflection_feedback": "",
            "reflection_count": 0,
            "working_memory": prior_state.values.get("working_memory", {"entries": []}) if prior_state else {"entries": []},
            "reflection_history": [],
            "task_difficulty": None,
            "total_cost_usd": 0.0,
            "_cost_breakdown": {},
            "_total_tokens": 0,
            "_prompt_versions": {},
            "self_consistency_samples": None,
            "calibration_data": {},
            "_max_concurrent_tasks": None,
            "_active_speculations": None,
            "_pending_splits": [],
            "_dag_generation": 0,
            "dag_tasks": [],
            "dag_results": {},
            "dag_phase": "",
            "_routing_decision": "continue",
            "tool_results_ref": "",
            "_ephemeral_keys": _EPHEMERAL_FIELDS,
            "is_high_risk": False,
            "_plan_repair_count": 0,
            "_tool_retry_count": 0,
            "_safety_result": {"passed": True, "action": "allow", "reason": ""},
            "_plan_valid": True,
            "_plan_validation_failures": [],
            "_invalid_results": [],
            "_split_tools": [],
            "completed_task_ids": [],
            "dag_iteration": 0,
            "reflection_revisions": 0,
            "max_dag_iterations": 5,
            "max_reflection_revisions": 3,
        }

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

        span = _tracer.start_span("agent.invoke")
        span.set_attribute("session_id", sid)
        span.set_attribute("model", initial_state.get("_model", ""))

        try:
            async for event in graph.astream(initial_state, run_config, stream_mode="updates"):
                node_name: str = next(iter(event))
                state_update: dict[str, Any] = event[node_name]
                _last_state.update(state_update)

                agent_events = self._translate(node_name, state_update)
                for agent_event in agent_events:
                    if self._event_bus:
                        await self._event_bus.publish(
                            agent_channel(sid),
                            agent_event.to_dict(),
                        )
                    yield agent_event

        except asyncio.CancelledError:
            logger.info("agent.run.cancelled", session_id=sid)
        except Exception as exc:
            _error_msg = str(exc)
            logger.error("agent.run.failed", exc_info=exc)
            error_event = AgentEvent("error", {"message": _error_msg})
            if self._event_bus:
                await self._event_bus.publish(agent_channel(sid), error_event.to_dict())
            yield error_event
        finally:
            span.end()
            # Persist outcome record (fire-and-forget)
            latency = int((time_module.perf_counter() - _start_ts) * 1000)
            try:
                outcome = InvocationOutcome.from_state(
                    _last_state, latency, error_message=_error_msg
                )
                # Fire and forget
                asyncio.ensure_future(persist_outcome(outcome))
            except Exception:
                pass
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
            if lock_acquired and redis is not None:
                await self._release_lock(redis, lock_key, lock_token)

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
        graph = self._build_graph()
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
    def _translate(node_name: str, state_update: dict[str, Any]) -> list[AgentEvent]:
        """Map a LangGraph state update to zero or more ``AgentEvent`` instances."""
        events: list[AgentEvent] = []

        # Handle subgraph-namespaced node names (e.g. "tool_subgraph:uuid:plan")
        # Extract the inner node name after the last colon
        inner_name = node_name.split(":")[-1] if ":" in node_name else node_name

        # Emit final_response only from finalize (which always runs last).
        fr = state_update.get("final_response")
        if fr is not None and inner_name == "finalize":
            events.append(AgentEvent("final_response", {"text": fr}))

        if inner_name == "understand_intent":
            intent = state_update.get("intent")
            if intent:
                etype = "tool_selected" if intent.get("intent") else "error"
                payload: dict[str, Any] = {
                    "intent": intent.get("intent"),
                    "parameters": intent.get("parameters", {}),
                }
                if not intent.get("intent") and state_update.get("final_response"):
                    meta_question = state_update["final_response"]
                    events.append(AgentEvent("clarification_needed", {"question": meta_question}))
                events.append(AgentEvent(etype, payload))

        elif inner_name == "reflect_on_response":
            score = state_update.get("reflection_score")
            if score is not None:
                events.append(
                    AgentEvent(
                        "reflection_result",
                        {
                            "score": score,
                            "feedback": state_update.get("reflection_feedback", ""),
                            "reflection_count": state_update.get("reflection_count", 0),
                        },
                    )
                )

        elif inner_name in ("review_plan", "review_final_answer"):
            fr = state_update.get("final_response")
            if fr is not None:
                event_type = "clarification_needed" if inner_name == "review_plan" else "interrupt"
                events.append(AgentEvent(event_type, {"question": fr, "source": inner_name}))

        elif inner_name == "self_consistency":
            samples = state_update.get("self_consistency_samples")
            if samples:
                events.append(AgentEvent("self_consistency_result", {"samples": samples}))
            final = state_update.get("final_response")
            if final:
                events.append(AgentEvent("clarification_needed", {"question": final}))

        elif inner_name == "gather_requirements":
            final = state_update.get("final_response")
            if final:
                events.append(AgentEvent("clarification_needed", {"question": final}))

        elif inner_name == "plan":
            plan = state_update.get("plan")
            if plan:
                events.append(AgentEvent("plan_created", {"steps": plan}))

        elif inner_name == "dag_expander":
            # Emit plan_created when DAG is first generated
            plan = state_update.get("plan")
            if plan:
                events.append(AgentEvent("plan_created", {"steps": plan}))

        elif inner_name == "dag_splitter":
            # Emit splitter event when new tasks are dynamically created
            new_tasks = state_update.get("_routing_decision")
            if new_tasks == "split":
                dag_gen = state_update.get("_dag_generation", 0)
                events.append(AgentEvent("plan_created", {"steps": state_update.get("dag_tasks", []), "generation": dag_gen}))

        elif inner_name == "tool_executor":
            # Emit tool_call_completed for each new tool result
            tool_results = state_update.get("tool_results", [])
            if tool_results:
                last = tool_results[-1]
                etype = "tool_call_completed" if last.get("status") == "success" else "error"
                events.append(
                    AgentEvent(
                        etype,
                        {
                            "tool_name": last.get("tool_name"),
                            "status": last.get("status"),
                            "data": last.get("data"),
                            "error": last.get("error"),
                            "task_id": last.get("task_id"),
                        },
                    )
                )

            # Emit approval_required if pending_approval is set
            pending = state_update.get("pending_approval")
            if pending and isinstance(pending, dict):
                events.append(AgentEvent("approval_required", pending))

        elif inner_name == "present_preview":
            data = state_update.get("final_response")
            if data:
                events.append(AgentEvent("intermediate_preview", {"text": data}))

        elif inner_name == "tool_subgraph":
            # Subgraph finished — emit events from accumulated state
            plan = state_update.get("plan")
            if plan:
                events.append(AgentEvent("plan_created", {"steps": plan}))
            tool_results = state_update.get("tool_results", [])
            if tool_results:
                last = tool_results[-1]
                events.append(
                    AgentEvent(
                        "tool_call_completed",
                        {
                            "tool_name": last.get("tool_name"),
                            "status": last.get("status"),
                            "data": last.get("data"),
                            "error": last.get("error"),
                        },
                    )
                )

        errors = state_update.get("errors", [])
        if errors and isinstance(errors, list):
            events.append(AgentEvent("error", {"errors": errors[-1:]}))

        return events
