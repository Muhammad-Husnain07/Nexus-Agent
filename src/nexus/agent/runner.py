"""AgentRunner — invoke the LangGraph graph and stream events."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import structlog
from langgraph.graph import StateGraph

from nexus.agent.graph import build_agent_graph
from nexus.agent.state import AgentState
from nexus.llm.client import LLMClient
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
            session_id=..., user_message=..., tenant_id=..., user_id=...
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
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._selector = tool_selector
        self._executor = tool_executor
        self._event_bus = event_bus
        self._session_factory = session_factory

    async def invoke(
        self,
        session_id: uuid.UUID | str,
        user_message: str,
        tenant_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
        config: dict[str, Any] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the agent graph and yield events.

        Args:
            session_id: The conversation session ID.
            user_message: The user's latest message.
            tenant_id: The tenant ID.
            user_id: The user ID.
            config: Optional LangGraph ``RunnableConfig`` dict
                (e.g. ``{"configurable": {"thread_id": ..., "tags": [...]}}``).

        Yields:
            ``AgentEvent`` instances as the graph progresses.
        """
        graph: StateGraph = build_agent_graph(
            llm_client=self._llm,
            tool_selector=self._selector,
            tool_executor=self._executor,
            event_bus=self._event_bus,
            session_factory=self._session_factory,
        )

        sid = str(session_id)
        tid = str(tenant_id)
        uid = str(user_id)

        initial_state: AgentState = {
            "messages": [{"role": "user", "content": user_message}],
            "tenant_id": tid,
            "session_id": sid,
            "user_id": uid,
            "plan": None,
            "current_step_index": 0,
            "gathered_requirements": {},
            "available_tools": [],
            "pending_approval": None,
            "iteration_count": 0,
            "scratchpad": "",
            "tool_results": [],
            "final_response": None,
            "intent": None,
            "missing_info_slots": None,
            "errors": [],
            "_routing_decision": "continue",
        }

        run_config: dict[str, Any] = dict(config or {})
        run_config.setdefault("configurable", {})["thread_id"] = sid

        try:
            async for event in graph.astream(initial_state, run_config, stream_mode="updates"):
                node_name: str = next(iter(event))
                state_update: dict[str, Any] = event[node_name]

                for agent_event in self._translate(node_name, state_update):
                    if self._event_bus:
                        await self._event_bus.publish(
                            agent_channel(sid),
                            agent_event.to_dict(),
                        )
                    yield agent_event
        except Exception as exc:
            logger.error("agent.run.failed", exc_info=exc)
            error_event = AgentEvent("error", {"message": str(exc)})
            if self._event_bus:
                await self._event_bus.publish(agent_channel(sid), error_event.to_dict())
            yield error_event

    @staticmethod
    def _translate(node_name: str, state_update: dict[str, Any]) -> list[AgentEvent]:
        """Map a LangGraph state update to zero or more ``AgentEvent`` instances."""
        events: list[AgentEvent] = []

        fr = state_update.get("final_response")
        if fr is not None:
            events.append(AgentEvent("final_response", {"text": fr}))

        if node_name == "understand_intent":
            intent = state_update.get("intent")
            if intent:
                etype = "tool_selected" if intent.get("intent") else "error"
                events.append(
                    AgentEvent(
                        etype,
                        {
                            "intent": intent.get("intent"),
                            "parameters": intent.get("parameters", {}),
                        },
                    )
                )

        elif node_name == "gather_requirements":
            final = state_update.get("final_response")
            if final:
                events.append(AgentEvent("clarification_needed", {"question": final}))

        elif node_name == "plan":
            plan = state_update.get("plan")
            if plan:
                events.append(AgentEvent("plan_created", {"steps": plan}))

        elif node_name == "execute_step":
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
                        },
                    )
                )

        elif node_name == "present_preview":
            data = state_update.get("final_response")
            if data:
                events.append(AgentEvent("intermediate_preview", {"text": data}))

        errors = state_update.get("errors", [])
        if errors and isinstance(errors, list):
            events.append(AgentEvent("error", {"errors": errors[-1:]}))

        return events
