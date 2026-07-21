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

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from nexus.agent.graph import build_agent_graph
from nexus.agent.state import AgentState
from nexus.llm.client import LLMClient
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
        except Exception:
            pass

        initial_state: AgentState = {
            "messages": prior_messages + [{"role": "user", "content": user_message}],
            "session_id": sid,
            "user_context": {},
            "plan": None,
            "current_step_index": 0,
            "gathered_requirements": prior_state.values.get("gathered_requirements", {}) if prior_state else {},
            "available_tools": [],
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
            "dag_tasks": [],
            "dag_results": {},
            "dag_phase": "",
            "_routing_decision": "continue",
        }

        redis = get_redis_client()
        lock_acquired = False
        lock_key = f"lock:agent_run:{sid}"
        lock_token = ""
        heartbeat_task: asyncio.Task[None] | None = None

        if redis is not None:
            from nexus.config.settings import get_settings  # noqa: PLC0415

            ttl = get_settings().agent.run_lock_ttl_s
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

        try:
            async for event in graph.astream(initial_state, run_config, stream_mode="updates"):
                node_name: str = next(iter(event))
                state_update: dict[str, Any] = event[node_name]
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
            logger.error("agent.run.failed", exc_info=exc)
            error_event = AgentEvent("error", {"message": str(exc)})
            if self._event_bus:
                await self._event_bus.publish(agent_channel(sid), error_event.to_dict())
            yield error_event
        finally:
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
            from nexus.config.settings import get_settings  # noqa: PLC0415

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
