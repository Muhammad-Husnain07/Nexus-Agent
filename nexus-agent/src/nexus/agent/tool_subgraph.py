"""Tool execution subgraph — DAG-based parallel execution pipeline.

Replaces the old sequential plan→select→execute→analyze loop with a
DAG-based parallel executor using LangGraph's ``Send()`` API.

The DAG pattern:
1. ``dag_expander`` generates a DAG of tasks (or advances to next batch)
2. ``route_dag`` conditional edge fans out ready tasks in parallel via ``Send()``
3. ``tool_executor`` executes a single task (no LLM — direct HTTP call)
4. Loop back to ``dag_expander`` until all tasks complete
5. Exit to parent's ``finalize``
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph

from nexus.agent.nodes import dag_expander as _dag_expander_fn
from nexus.agent.nodes import dag_splitter as _dag_splitter_fn
from nexus.agent.nodes import discover_tools as _discover_tools_fn
from nexus.agent.nodes import plan_repair as _plan_repair_fn
from nexus.agent.nodes import plan_validator as _plan_validator_fn
from nexus.agent.nodes import result_validator as _result_validator_fn
from nexus.agent.nodes import risk_gate as _risk_gate_fn
from nexus.agent.nodes import route_dag as _route_dag_fn
from nexus.agent.nodes import tool_executor as _tool_exec_fn
from nexus.agent.state import AgentState
from nexus.llm.client import LLMClient
from nexus.redis_client.pubsub import EventBus
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor


def _node(fn: Any, *args: Any, **kwargs: Any) -> Callable[[AgentState], Any]:
    """Wrap a node function with pre-bound dependencies."""

    async def wrapper(state: AgentState) -> dict[str, Any]:
        return await fn(state, *args, **kwargs)

    return wrapper


def build_tool_subgraph(
    tool_selector: DynamicToolSelector,
    tool_executor: ToolExecutor,
    llm_client: LLMClient,
    model: str,
    settings: Any,
    event_bus: EventBus | None = None,
    session_factory: Callable[[], Any] | None = None,
) -> StateGraph:
    """Build the DAG-based tool execution subgraph.

    All nodes share ``AgentState`` with the parent graph.  The subgraph
    inherits the parent's checkpointer (per-invocation persistence).

    Returns:
        A compiled ``StateGraph`` ready to be used as a node in the parent.
    """
    builder = StateGraph(AgentState)

    # Add nodes
    builder.add_node("discover_tools", _node(_discover_tools_fn, tool_selector, session_factory))
    builder.add_node("dag_expander", _node(_dag_expander_fn, llm_client, model))
    builder.add_node("plan_validator", _node(_plan_validator_fn))
    builder.add_node("plan_repair", _node(_plan_repair_fn))
    builder.add_node("risk_gate", _node(_risk_gate_fn))
    builder.add_node("tool_executor", _node(_tool_exec_fn, session_factory))
    builder.add_node("result_validator", _node(_result_validator_fn))
    builder.add_node("dag_splitter", _node(_dag_splitter_fn, llm_client, model))

    builder.set_entry_point("discover_tools")

    # Discover tools → then expand DAG
    builder.add_edge("discover_tools", "dag_expander")

    # After dag_expander, validate plan before execution
    builder.add_edge("dag_expander", "plan_validator")

    # After plan_validator: route to repair or continue
    def route_after_validation(state: AgentState) -> str:
        valid = state.get("_plan_valid", True)
        repair_count = state.get("_plan_repair_count", 0)
        if not valid and repair_count < 2:
            return "plan_repair"
        if not valid:
            return "ask"
        return "risk_gate"

    builder.add_conditional_edges(
        "plan_validator",
        route_after_validation,
        {
            "risk_gate": "risk_gate",
            "plan_repair": "plan_repair",
            "ask": END,
        },
    )

    # plan_repair loops back to plan_validator for re-validation
    def route_after_repair(state: AgentState) -> str:
        decision = state.get("_routing_decision", "ask")
        if decision == "continue":
            return "plan_validator"
        return "ask"

    builder.add_conditional_edges(
        "plan_repair",
        route_after_repair,
        {
            "plan_validator": "plan_validator",
            "ask": END,
        },
    )

    # After risk_gate, route_dag fans out via Send() to tool_executor
    # route_dag handles invalid plan abort internally (returns "ask")
    builder.add_conditional_edges(
        "risk_gate",
        _route_dag_fn,
        {
            "tool_executor": "tool_executor",
            "finalize": "dag_splitter",
            "ask": END,
        },
    )

    # After tool_executor (parallel), validate results
    builder.add_edge("tool_executor", "result_validator")

    # Then route through dag_splitter
    builder.add_edge("result_validator", "dag_splitter")

    # After dag_splitter, either loop back to dag_expander (if split or if
    # there are pending tasks whose dependencies are now satisfied), or exit.
    def route_after_splitter(state: AgentState) -> str:
        if state.get("_routing_decision") == "split":
            return "dag_expander"
        # Check for unexecuted tasks whose dependencies are now met.
        # Without this check, tasks with dependencies (e.g. get_weather
        # depending on get_geocoding) would never execute because route_dag
        # only runs once before the first batch.
        tasks: list[dict[str, Any]] = state.get("dag_tasks", [])
        results: dict[str, Any] = state.get("dag_results", {})
        remaining = [t for t in tasks if t["id"] not in results]
        if remaining:
            for t in remaining:
                deps = t.get("depends_on", [])
                if all(d in results for d in deps):
                    logger.info("tool_subgraph.route_after_splitter.has_pending_ready",
                                task=t["id"], tool=t.get("tool_name"))
                    return "dag_expander"
        return END

    builder.add_conditional_edges(
        "dag_splitter",
        route_after_splitter,
        {
            "dag_expander": "dag_expander",
            END: END,
        },
    )

    return builder.compile(checkpointer=None)
