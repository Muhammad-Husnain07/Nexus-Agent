"""LangGraph StateGraph — hybrid ReAct + Plan-and-Execute orchestration.

Nodes (parent graph):
* ``understand_intent`` — parse user message into structured intent
* ``gather_requirements`` — ask clarifying questions when info is missing
* ``respond_without_tool`` — direct responses for non-tool queries
* ``tool_subgraph`` — DAG-based parallel tool execution subgraph
* ``finalize`` — compose the final answer
* ``review_final_answer`` — interrupt for final approval
* ``reflect_on_response`` — self-score and improve the response

Tool execution lives in ``tool_subgraph`` (see ``tool_subgraph.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from nexus.agent.nodes import (
    finalize,
    gather_requirements,
    reflect_on_response,
    respond_without_tool,
    review_final_answer,
    self_consistency,
    understand_intent,
)
from nexus.agent.state import AgentState
from nexus.agent.tool_subgraph import build_tool_subgraph
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient
from nexus.redis_client.pubsub import EventBus

from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_understand(state: AgentState) -> str:
    """Route based on response type, missing info, and confidence band.

    Priority:
    1. Non-tool queries (greeting/meta/memory) → respond_without_tool
    2. Missing info slots → gather_requirements (clarify)
    3. Low confidence (< 0.5) → gather_requirements
    4. Moderate confidence (0.5–0.7) → self_consistency
    5. High confidence → discover_tools
    """
    resp_type: str = state.get("response_type", "tool")
    if resp_type in ("greeting", "meta", "memory_query"):
        return "respond_without_tool"
    missing: list[str] = state.get("missing_info_slots") or []
    if missing:
        return "gather_requirements"

    # Check routing decision set by understand_intent
    routing: str = state.get("_routing_decision", "")
    if routing == "self_consistency":
        return "self_consistency"

    return "discover_tools"


def route_after_reflection(state: AgentState) -> str:
    """Route based on reflection decision or max rounds reached."""
    decision: str = state.get("_routing_decision", "finalize")
    if decision == "clarify":
        return "clarify"
    if decision in ("revise_finalize", "revise"):
        return decision
    return "finalize"


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

    graph = StateGraph(AgentState)

    # Build the tool execution subgraph
    tool_subgraph = build_tool_subgraph(
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        llm_client=_llm,
        model=_model,
        settings=_settings,
        event_bus=event_bus,
        session_factory=session_factory,
    )
    graph.add_node("tool_subgraph", tool_subgraph)

    graph.add_node("understand_intent", _node(understand_intent, _llm, _model))
    graph.add_node("self_consistency", _node(self_consistency, _llm, _model))
    graph.add_node("respond_without_tool", _node(respond_without_tool, _llm, _model))
    graph.add_node("gather_requirements", _node(gather_requirements, _llm, _model))
    graph.add_node("finalize", _node(finalize, _llm, _model, session_factory))
    graph.add_node("review_final_answer", _node(review_final_answer))
    graph.add_node("reflect_on_response", _node(reflect_on_response, _llm, _model))

    graph.set_entry_point("understand_intent")

    graph.add_conditional_edges(
        "understand_intent",
        route_after_understand,
        {
            "respond_without_tool": "respond_without_tool",
            "gather_requirements": "gather_requirements",
            "discover_tools": "tool_subgraph",
            "self_consistency": "self_consistency",
        },
    )

    # Self-consistency routes based on agreement
    graph.add_conditional_edges(
        "self_consistency",
        lambda s: s.get("_routing_decision", "ask"),
        {
            "proceed": "tool_subgraph",
            "ask": "gather_requirements",
        },
    )

    graph.add_edge("respond_without_tool", "finalize")
    graph.add_edge("gather_requirements", END)

    # Conditional routing after tool subgraph exits
    def route_after_tool_subgraph(state: AgentState) -> str:
        decision: str = state.get("_routing_decision", "finalize")
        if decision == "ask":
            return "gather_requirements"
        return "finalize"

    graph.add_conditional_edges(
        "tool_subgraph",
        route_after_tool_subgraph,
        {
            "finalize": "finalize",
            "gather_requirements": "gather_requirements",
        },
    )

    graph.add_edge("finalize", "review_final_answer")

    graph.add_conditional_edges(
        "review_final_answer",
        lambda s: s.get("_routing_decision", "continue"),
        {
            "continue": "reflect_on_response",
            "revise": "understand_intent",
            "finalize": END,
        },
    )

    graph.add_conditional_edges(
        "reflect_on_response",
        route_after_reflection,
        {
            "revise_finalize": "finalize",
            "revise": "understand_intent",
            "clarify": "gather_requirements",
            "finalize": END,
        },
    )

    _cp = checkpointer or MemorySaver()
    return graph.compile(checkpointer=_cp)
