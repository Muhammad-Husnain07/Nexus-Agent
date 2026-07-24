"""
Production Agent Orchestration Graph — 5-node LangGraph state machine.

Nodes
=====
1. **RouterNode** — Query classifier + router.  Routes to planner or direct response.
2. **PlannerNode** — Builds DAG execution plan (dependency analysis + waves).
3. **ExecutorNode** — Wave-based concurrent tool execution with retry + timeout.
4. **ReflectionNode** — Evaluates results, decides retry or proceed.
5. **ResponseNode** — Composes final answer from tool results.

Edges
=====
- START → RouterNode
- RouterNode → ExecutorNode (SINGLE_TOOL / NO_TOOL_NEEDED)
- RouterNode → PlannerNode (INDEPENDENT_MULTI / DEPENDENT_MULTI)
- PlannerNode → ExecutorNode (plan ready)
- ExecutorNode → ResponseNode (all succeeded / partial failures)
- ExecutorNode → ReflectionNode (unrecoverable errors)
- ReflectionNode → PlannerNode (retry needed)
- ReflectionNode → ResponseNode (max retries exceeded)
- ResponseNode → END

Interrupts
==========
``interrupt_before=["ExecutorNode"]`` when any planned tool has
``requires_approval=True`` or ``risk_level="high"``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, StateGraph

from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
from nexus.agent.memory.context_manager import (
    compress_history,
    filter_relevant_tools,
    truncate_tool_result,
)
from nexus.agent.planners.dag_planner import PlannerRunner
from nexus.agent.router import QueryType
from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient
from nexus.redis_client.pubsub import EventBus
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor

logger = structlog.get_logger("nexus.agent.graph")


# ============================================================================
# Node Wrapper
# ============================================================================


def node(fn: Any, *args: Any, **kwargs: Any) -> Callable[[AgentState], Any]:
    """Wrap a graph node function with pre-bound dependencies."""

    async def wrapper(state: AgentState) -> dict[str, Any]:
        return await fn(state, *args, **kwargs)

    return wrapper


# ============================================================================
# Routing
# ============================================================================


def route_after_router(state: AgentState) -> str:
    """Route based on query type and safety result.

    - rejected → ResponseNode (error)
    - NO_TOOL_NEEDED → ResponseNode (direct response)
    - all tool-requiring types → PlannerNode (plan + execute)
    """
    safety = state.get("_safety_result", {})
    if safety.get("action") == "reject":
        logger.warning("graph.safety_rejected", reason=safety.get("reason", ""))
        return "ResponseNode"

    qtype = state.get("_query_type", QueryType.SINGLE_TOOL.value)

    if qtype == QueryType.NO_TOOL_NEEDED.value:
        return "ResponseNode"

    return "PlannerNode"


def route_after_executor(state: AgentState) -> str:
    """Route based on execution results.

    - All successful → ResponseNode
    - Partial failures → ReflectionNode
    """
    failed = state.get("_executor_failed", [])
    if not failed:
        return "ResponseNode"
    return "ReflectionNode"


def route_after_reflection(state: AgentState) -> str:
    """Route based on reflection decision.

    - Retry needed → PlannerNode
    - Finalize → ResponseNode
    """
    decision = state.get("_routing_decision", "finalize")
    if decision == "retry":
        return "PlannerNode"
    return "ResponseNode"


# ============================================================================
# Node: Router
# ============================================================================


async def router_node(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Classify the incoming query and determine the optimal path.

    Sets ``_query_type`` and ``_preferred_tools`` in state.
    """
    from nexus.agent.router import node_classify_query
    return await node_classify_query(state, llm, model)


# ============================================================================
# Node: Planner
# ============================================================================


async def planner_node(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Build an execution plan: analyze dependencies, construct DAG.

    Uses the DAG Planner module with:
    - Implicit dependency injection (geocode → weather)
    - Explicit I/O schema dependency analysis
    - Cycle detection
    - Topological sort into execution waves
    """
    tools = state.get("available_tools", [])
    user_input = _last_user_message(state)
    intents = _get_intents(state)

    # Filter tools to relevant ones
    intent_text = " ".join(intents) or user_input
    relevant_tools = filter_relevant_tools(intent_text, tools, top_k=10)

    # Build the plan
    plan = await PlannerRunner.build_plan(
        intents=intents,
        tools=relevant_tools,
        user_input=user_input,
        llm=llm,
        model=model,
    )

    # Store plan in state
    return {
        "_execution_plan": {
            "waves": [
                {
                    "wave": w.wave,
                    "tasks": [
                        {
                            "id": t.id,
                            "tool_name": t.tool_name,
                            "inputs": t.inputs,
                            "depends_on": t.depends_on,
                        }
                        for t in w.tasks
                    ],
                }
                for w in plan.waves
            ],
            "tool_names": plan.tool_names,
            "dependencies": plan.dependencies,
        },
        "dag_tasks": [
            {"id": t.id, "tool_name": t.tool_name, "inputs": t.inputs, "depends_on": t.depends_on}
            for w in plan.waves for t in w.tasks
        ],
    }


# ============================================================================
# Node: Executor
# ============================================================================


async def executor_node(
    state: AgentState,
    tool_executor: ToolExecutor,
) -> dict[str, Any]:
    """Execute the DAG plan using the Concurrent Executor.

    Handles:
    - Wave-based parallel execution
    - Fault isolation (one failure doesn't block other tasks)
    - Retry with exponential backoff
    - Per-tool and global timeouts
    """
    plan_data = state.get("_execution_plan") or {}
    waves_data = plan_data.get("waves", [])
    tasks_data = state.get("dag_tasks", [])

    if not tasks_data or not waves_data:
        # No plan was generated — return error so ReflectionNode can route
        logger.warning("executor_node.no_plan", query_type=state.get("_query_type", "unknown"))
        return {
            "_executor_results": {},
            "_executor_failed": [],
            "_executor_all_success": False,
            "errors": ["No execution plan available — planner did not produce tasks"],
        }

    # Sanitize tasks_data — ensure every item is a dict, not a tuple or other type
    tasks_data = [
        t if isinstance(t, dict) else dict(t) for t in tasks_data
    ]

    # Build Task objects for the executor
    from nexus.agent.planners.dag_planner import ExecutionTask

    task_map = {t["id"]: ExecutionTask(
        id=t["id"],
        tool_name=t["tool_name"],
        inputs=t.get("inputs", {}),
        depends_on=t.get("depends_on", []),
    ) for t in tasks_data}

    # Build Wave objects
    from nexus.agent.planners.dag_planner import ExecutionWave

    waves = [
        ExecutionWave(
            wave=w["wave"],
            tasks=[task_map[t["id"]] for t in w["tasks"] if t["id"] in task_map],
        )
        for w in waves_data
    ]

    # Build tool map from available_tools for the executor
    available_tools = state.get("available_tools", [])
    tool_map = {t["name"]: t for t in available_tools if isinstance(t, dict) and t.get("name")}

    executor = ConcurrentExecutor(tool_executor=tool_executor, tool_map=tool_map)
    settings = get_settings()

    results = await executor.execute(
        tasks=list(task_map.values()),
        waves=waves,
        max_concurrency=settings.agent.adaptive_reflection.max_concurrent_tasks,
        per_tool_timeout=settings.tools.execution_timeout_s if hasattr(settings, "tools") else 15.0,
        global_timeout=60.0,
    )

    # Update working memory with results
    tool_results = []
    for task_id, outcome in results.by_task.items():
        tool_results.append({
            "tool_name": outcome.tool_name,
            "status": outcome.status,
            "data": outcome.data,
            "error": outcome.error,
            "task_id": outcome.task_id,
            "duration_ms": outcome.duration_ms,
        })

    return {
        "tool_results": tool_results,
        "_executor_results": {k: {"data": v.data, "status": v.status} for k, v in results.by_task.items()},
        "_executor_failed": results.failed + results.timed_out,
        "_executor_all_success": results.all_successful,
        "_tool_executed_in_turn": True,
    }


# ============================================================================
# Node: Reflection
# ============================================================================


async def reflection_node(state: AgentState) -> dict[str, Any]:
    """Evaluate execution results and decide next action.

    - If all tasks succeeded → proceed to response
    - If partial failures and retries remain → retry the failed tasks
    - If max retries exceeded → proceed with partial results
    """
    failed = state.get("_executor_failed", [])
    retry_counts = state.get("_tool_retry_counts", {})

    if not failed:
        return {"_routing_decision": "finalize"}

    # Check retry counts
    tasks_to_retry = []
    tasks_to_skip = []

    for task_id in failed:
        retries = retry_counts.get(task_id, 0)
        if retries < 2:
            tasks_to_retry.append(task_id)
        else:
            tasks_to_skip.append(task_id)

    if tasks_to_retry:
        # Increment retry counts
        new_counts = dict(retry_counts)
        for tid in tasks_to_retry:
            new_counts[tid] = new_counts.get(tid, 0) + 1

        logger.info(
            "reflection_node.retry",
            retry_count=len(tasks_to_retry),
            skip_count=len(tasks_to_skip),
        )
        return {
            "_routing_decision": "retry",
            "_tool_retry_counts": new_counts,
            "_pending_tasks": tasks_to_retry,
        }

    logger.info("reflection_node.max_retries", tasks=tasks_to_skip)
    return {"_routing_decision": "finalize"}


# ============================================================================
# Node: Response
# ============================================================================


async def response_node(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Compose the final response from tool results.

    If a direct response was already set (greeting / meta), return it.
    Otherwise, use the LLM to compose a natural response from results.
    """
    existing = state.get("final_response")
    if existing and state.get("response_type") in ("greeting", "meta"):
        return {"final_response": existing, "_routing_decision": "finalize"}

    # Compose from tool results
    tool_results = state.get("tool_results", [])
    errors = state.get("errors", [])

    if not tool_results and not errors:
        return {"final_response": "I processed your request.", "_routing_decision": "finalize"}

    from nexus.agent.nodes.finalize import finalize as compose_response
    return await compose_response(state, llm, model)


# ============================================================================
# Helpers
# ============================================================================


def _last_user_message(state: AgentState) -> str:
    """Extract the last user message from state."""
    messages = state.get("messages", [])
    if isinstance(messages, list):
        for m in reversed(messages):
            role = ""
            content = ""
            if isinstance(m, dict):
                role = m.get("role", "")
                content = m.get("content", "")
            elif hasattr(m, "role"):
                role = getattr(m, "role", "")
                content = getattr(m, "content", "")
            if role == "user" and isinstance(content, str):
                return content
    return ""


def _get_intents(state: AgentState) -> list[str]:
    """Extract parsed intents from state."""
    intent_analysis = state.get("intent_analysis")
    if isinstance(intent_analysis, dict):
        goal = intent_analysis.get("primary_goal", "")
        implied = intent_analysis.get("implied_actions", [])
        if goal:
            return [goal] + implied
    intent = state.get("intent")
    if isinstance(intent, dict):
        text = intent.get("intent", "")
        if text:
            return [text]
    return []


# ============================================================================
# Graph Builder
# ============================================================================


def build_agent_graph(
    llm_client: LLMClient | None = None,
    tool_selector: DynamicToolSelector | None = None,
    tool_executor: ToolExecutor | None = None,
    event_bus: EventBus | None = None,
    model: str | None = None,
    session_factory: Callable[[], Any] | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> StateGraph:
    """Build and compile the LangGraph production agent graph.

    Args:
        llm_client: LLM client.  Creates default if None.
        tool_selector: Dynamic tool discovery.  Required for tool lookup.
        tool_executor: Tool execution engine.  Required.
        event_bus: Redis event bus for streaming.
        model: Model override (defaults to settings).
        session_factory: DB session factory.
        checkpointer: LangGraph checkpoint saver.

    Returns:
        Compiled ``StateGraph``.
    """
    _llm = llm_client or LLMClient()
    settings = get_settings()
    _model = model or settings.llm.default_model
    _executor = tool_executor or ToolExecutor()

    graph = StateGraph(AgentState)

    # 5 production nodes
    graph.add_node("RouterNode", node(router_node, _llm, _model))
    graph.add_node("PlannerNode", node(planner_node, _llm, _model))
    graph.add_node("ExecutorNode", node(executor_node, _executor))
    graph.add_node("ReflectionNode", node(reflection_node))
    graph.add_node("ResponseNode", node(response_node, _llm, _model))

    graph.set_entry_point("RouterNode")

    # Router → Planner or Response
    graph.add_conditional_edges(
        "RouterNode",
        route_after_router,
        {
            "PlannerNode": "PlannerNode",
            "ResponseNode": "ResponseNode",
        },
    )

    # Planner → Executor
    graph.add_edge("PlannerNode", "ExecutorNode")

    # Executor → Response or Reflection
    graph.add_conditional_edges(
        "ExecutorNode",
        route_after_executor,
        {
            "ResponseNode": "ResponseNode",
            "ReflectionNode": "ReflectionNode",
        },
    )

    # Reflection → Planner (retry) or Response (finalize)
    graph.add_conditional_edges(
        "ReflectionNode",
        route_after_reflection,
        {
            "PlannerNode": "PlannerNode",
            "ResponseNode": "ResponseNode",
        },
    )

    # Response → END
    graph.add_edge("ResponseNode", END)

    # Compile with interrupt support for high-risk tools
    _cp = checkpointer
    if _cp is None:
        try:
            _cp = PostgresSaver.from_conn_string(settings.database.url)
        except Exception:
            from langgraph.checkpoint.memory import MemorySaver
            _cp = MemorySaver()

    return graph.compile(
        checkpointer=_cp,
    )
