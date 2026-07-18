"""LangGraph StateGraph — hybrid ReAct + Plan-and-Execute orchestration.

Nodes
-----
* ``understand_intent`` — parse user message into structured intent
* ``gather_requirements`` — ask clarifying questions when info is missing
* ``discover_tools`` — find relevant tools via ``DynamicToolSelector``
* ``plan`` — generate a step-by-step plan via LLM structured output
* ``select_and_bind_tools`` — pre-filter tools for the current plan step
* ``execute_step`` — ReAct micro-loop for the current plan step
* ``present_preview`` — interrupt for human feedback on intermediate results
* ``analyze_results`` — review results and decide next action
* ``finalize`` — compose the final answer

All node implementations live in ``nodes/`` modules.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from nexus.agent.nodes import (
    analyze_results,
    discover_tools,
    execute_step,
    finalize,
    gather_requirements,
    plan,
    present_preview,
    select_and_bind_tools,
    understand_intent,
)
from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient
from nexus.redis_client.pubsub import EventBus
from nexus.security.cost_control import CostController
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_understand(state: AgentState) -> str:
    """If missing_info_slots is non-empty, ask clarifying questions."""
    missing: list[str] = state.get("missing_info_slots") or []
    if missing:
        return "gather_requirements"
    return "discover_tools"


def route_after_analyze(state: AgentState) -> str:
    """Route to the next node based on the analyzer's decision."""
    decision: str = state.get("_routing_decision", "finalize")
    max_iter: int = get_settings().agent.max_iterations
    if state.get("iteration_count", 0) >= max_iter:
        return "finalize"
    if decision == "preview":
        return "present_preview"
    return decision


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _node(fn: Any, *args: Any, **kwargs: Any) -> Callable[[AgentState], Any]:
    """Wrap a node function with pre-bound dependencies."""

    async def wrapper(state: AgentState) -> dict[str, Any]:
        return await fn(state, *args, **kwargs)

    return wrapper


def build_agent_graph(  # noqa: PLR0913
    llm_client: LLMClient | None = None,
    tool_selector: DynamicToolSelector | None = None,
    tool_executor: ToolExecutor | None = None,
    event_bus: EventBus | None = None,
    model: str | None = None,
    session_factory: Callable[[], Any] | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> StateGraph:
    """Build and compile the LangGraph agent graph.

    Args:
        llm_client: LLM client for completions.  Creates a default if None.
        tool_selector: Dynamic tool discovery.  Required.
        tool_executor: Tool execution engine.  Required.
        event_bus: Redis event bus for streaming events.
        model: Model override (defaults to ``settings.llm.default_model``).
        session_factory: Async callable returning a DB ``AsyncSession``.

    Returns:
        A compiled ``StateGraph`` ready for invocation.
    """
    _llm = llm_client or LLMClient()
    settings = get_settings()
    _model = model or settings.llm.default_model
    _settings = settings.agent
    _cost_ctrl = CostController()

    graph = StateGraph(AgentState)

    graph.add_node("understand_intent", _node(understand_intent, _llm, _model))
    graph.add_node("gather_requirements", _node(gather_requirements, _llm, _model))
    graph.add_node("discover_tools", _node(discover_tools, tool_selector, session_factory))
    graph.add_node("plan", _node(plan, _llm, _model, _settings))
    graph.add_node("select_and_bind_tools", _node(select_and_bind_tools))
    graph.add_node(
        "execute_step",
        _node(execute_step, _llm, tool_executor, _model, _settings, event_bus, session_factory, cost_controller=_cost_ctrl),
    )
    graph.add_node("present_preview", _node(present_preview))
    graph.add_node("analyze_results", _node(analyze_results, _llm, _model))
    graph.add_node("finalize", _node(finalize, _llm, _model))

    graph.set_entry_point("understand_intent")

    graph.add_conditional_edges(
        "understand_intent",
        route_after_understand,
        {"gather_requirements": "gather_requirements", "discover_tools": "discover_tools"},
    )

    graph.add_edge("gather_requirements", END)
    graph.add_edge("discover_tools", "plan")
    graph.add_edge("plan", "select_and_bind_tools")
    graph.add_edge("select_and_bind_tools", "execute_step")
    graph.add_edge("execute_step", "analyze_results")

    graph.add_conditional_edges(
        "analyze_results",
        route_after_analyze,
        {
            "continue": "select_and_bind_tools",
            "revise": "plan",
            "ask": "gather_requirements",
            "preview": "present_preview",
            "finalize": "finalize",
        },
    )

    graph.add_conditional_edges(
        "present_preview",
        lambda s: s.get("_routing_decision", "continue"),
        {
            "continue": "select_and_bind_tools",
            "revise": "select_and_bind_tools",
            "finalize": "finalize",
        },
    )

    graph.add_edge("finalize", END)

    _cp = checkpointer or MemorySaver()
    return graph.compile(checkpointer=_cp)
