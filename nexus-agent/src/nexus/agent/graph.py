"""
Deterministic Workflow Compiler Graph — 13-node deterministic pipeline.

Nodes
=====
1.  **RouterNode** — Query classifier. Routes conversational → ResponseNode; workflow → SemanticPlannerNode.
2.  **SemanticPlannerNode** — LLM → ``LogicalWorkflow`` via capability catalog.
3.  **CompilerNode** — Deterministic codegen: LogicalWorkflow → ExecutionGraph.
4.  **OptimizerNode** — PassManager fixpoint optimizer on ExecutionGraph.
5.  **EstimatorNode** — Cost/latency estimation & budget check.
6.  **ValidationNode** — Schema/constraint validation of the optimized graph.
7.  **ClarificationNode** — Asks for missing info, ends graph.
8.  **ApprovalGateNode** — HITL check per tool risk level.
9.  **ExecutorNode** — Wave-based concurrent tool execution with retry.
10. **AggregatorNode** — Pure Python ReduceNode execution.
11. **ReflectionNode** — Graph diffing & patching for failed tasks.
12. **ResponseNode** — LLM narrative from tool results.
13. **MemoryHelperNode** — Persist to pgvector long-term memory.

Pipeline
========
RouterNode
  |-> SemanticPlannerNode -> CompilerNode -> OptimizerNode -> EstimatorNode -> ValidationNode
  |     |-> ApprovalGateNode -> ExecutorNode -> AggregatorNode -> ReflectionNode
  |     |     |-> ExecutorNode (retry sub-graph)
  |     |     |-> ResponseNode -> MemoryHelperNode -> END
  |     |-> ClarificationNode -> END
  |-> ResponseNode -> MemoryHelperNode -> END
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph

from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
from nexus.agent.router import QueryType
from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.execution.event_emitter import emit_wave_completed, emit_execution_finished
from nexus.llm.client import LLMClient
from nexus.redis_client.pubsub import EventBus
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor

logger = structlog.get_logger("nexus.agent.graph")


# ============================================================================
# Node Wrapper — binds dependencies to a graph node function
# ============================================================================


def node(fn: Any, *args: Any, **kwargs: Any) -> Callable[[AgentState], Any]:
    """Wrap a graph node function with pre-bound dependencies.

    The returned wrapper passes ``(state, *args, **kwargs)`` to ``fn``.
    Immutability enforcement is applied per-node by the ``@context_node`` decorator.
    """

    async def wrapper(state: AgentState) -> dict[str, Any]:
        return await fn(state, *args, **kwargs)

    return wrapper


# ============================================================================
# Routing (4 conditional edges)
# ============================================================================


def route_after_router(state: AgentState) -> str:
    """Route based on query type.

    - conversational / NO_TOOL_NEEDED → ResponseNode
    - workflow / tool-requiring → SemanticPlannerNode
    """
    safety = state.get("_safety_result", {})
    if safety.get("action") == "reject":
        logger.warning("graph.safety_rejected", reason=safety.get("reason", ""))
        return "ResponseNode"

    qtype = state.get("_query_type", QueryType.SINGLE_TOOL.value)
    if qtype == QueryType.NO_TOOL_NEEDED.value:
        return "ResponseNode"

    return "SemanticPlannerNode"


def route_after_validation(state: AgentState) -> str:
    """Route based on validation result.

    - empty workflow (0 nodes) → ResponseNode (conversational follow-up)
    - valid → ApprovalGateNode (proceed to HITL check)
    - invalid → ClarificationNode (missing info, ends graph)
    """
    workflow = state.get("_logical_workflow", {})
    nodes = workflow.get("nodes", []) if isinstance(workflow, dict) else []
    if len(nodes) == 0:
        logger.info("graph.route_empty_workflow")
        return "ResponseNode"

    if state.get("_ready_to_plan") is False:
        return "ClarificationNode"

    errors = state.get("errors", [])
    if errors and _has_validation_errors(errors):
        return "ClarificationNode"

    return "ApprovalGateNode"


def route_after_approval(state: AgentState) -> str:
    """Route based on approval gate decision.

    - approved → ExecutorNode
    - rejected / not granted → ResponseNode
    """
    granted = state.get("_approval_granted", True)
    decision = state.get("_approval_decision")
    if decision == "rejected" or granted is False:
        return "ResponseNode"
    return "ExecutorNode"


def route_after_reflection(state: AgentState) -> str:
    """Route based on reflection decision.

    - retry → ExecutorNode (retry only failed sub-graph)
    - finalize → ResponseNode
    """
    decision = state.get("_routing_decision", "finalize")
    if decision == "retry":
        return "ExecutorNode"
    return "ResponseNode"


def _has_validation_errors(errors: list) -> bool:
    """Check if any error is a validation/clarification error vs a runtime error.

    Keywords come from ``settings.agent.validation_error_keywords``.
    """
    from nexus.config.settings import get_settings as _g_settings
    try:
        keywords = _g_settings().agent.validation_error_keywords
    except Exception:
        keywords = ["missing", "required", "invalid", "clarification", "validation"]
    for err in errors:
        if isinstance(err, str) and any(kw in err.lower() for kw in keywords):
            return True
    return False


# ============================================================================
# MapNode helpers
# ============================================================================


def _expand_map_inputs(inputs: dict, item: Any) -> dict:
    """Dynamically substitute the iteration item into the tool inputs recursively.

    Recursively walks the entire inputs tree (dicts, lists, strings) and
    replaces:
    - ``"${item}"`` → the raw item value
    - ``"${item.field}"`` → ``item["field"]``
    - ``"${item.field.sub}"`` → ``item["field"]["sub"]``
    - Inline like ``"https://example.com/${item.id}"`` → resolved URL

    No structural assumptions about input shape — works at any depth.
    """
    return _substitute_item(inputs, item)


def _substitute_item(obj: Any, item: Any) -> Any:
    """Recursively walk and substitute ``${item}`` / ``${item.field}`` placeholders."""
    import re as _re

    if isinstance(obj, dict):
        return {k: _substitute_item(v, item) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_item(elem, item) for elem in obj]
    if isinstance(obj, str) and "${item" in obj:
        if obj == "${item}":
            return item
        m = _re.match(r"^\$\{item\.(.+)\}$", obj)
        if m:
            path = m.group(1).split(".")
            val: Any = item
            for p in path:
                if isinstance(val, dict) and p in val:
                    val = val[p]
                else:
                    return obj
            return val
        # Inline replacement: "https://example.com/${item.id}"
        def _inline_replacer(m: _re.Match) -> str:
            path = m.group(1).split(".")
            v: Any = item
            for p in path:
                if isinstance(v, dict) and p in v:
                    v = v[p]
                else:
                    return m.group(0)
            return str(v) if v is not None else m.group(0)
        return _re.sub(r"\$\{item\.([a-zA-Z0-9_.]+)\}", _inline_replacer, obj)
    return obj


# ============================================================================
# Node: Router
# ============================================================================


async def router_node(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Classify the incoming query and determine the optimal path."""
    from nexus.agent.router import node_classify_query

    return await node_classify_query(state, llm, model)


# ============================================================================
# Node: Approval Gate
# ============================================================================


async def approval_gate_node(state: AgentState) -> dict[str, Any]:
    """Check if any planned tool requires human approval."""
    graph_data = state.get("_optimized_graph") or state.get("_execution_graph")
    available_tools = state.get("available_tools", [])

    if not graph_data or not available_tools:
        return {"_approval_granted": True}

    # Extract tool names from the compiled graph
    nodes = graph_data.get("nodes", {}) if isinstance(graph_data, dict) else {}
    tool_names = list({
        nd.get("tool_name", "") for nd in nodes.values()
        if isinstance(nd, dict) and nd.get("tool_name")
    })

    if not tool_names:
        return {"_approval_granted": True}

    from nexus.tools.approval_gate import check_plan_approval, format_approval_message

    task_inputs: dict[str, list[dict[str, Any]]] = {}
    for nd in nodes.values():
        if isinstance(nd, dict):
            tool = nd.get("tool_name", "")
            if tool:
                task_inputs.setdefault(tool, []).append(nd.get("inputs", {}))

    pending = check_plan_approval(tool_names, available_tools)
    if not pending:
        return {"_approval_granted": True}

    decision = state.get("_approval_decision")
    if decision == "approved":
        return {
            "_approval_granted": True,
            "_approval_decision": None,
            "_needs_approval": False,
        }
    if decision == "rejected":
        return {
            "_approval_granted": False,
            "_approval_decision": None,
            "_needs_approval": False,
            "errors": ["Tool execution rejected by user"],
        }

    import time as _time

    requested_at = state.get("_approval_requested_at")
    if requested_at is not None:
        expiry = get_settings().agent.run_lock_ttl_s
        if _time.time() - requested_at > expiry:
            return {
                "_approval_granted": False,
                "_approval_decision": None,
                "_needs_approval": False,
                "errors": ["Approval request has expired — please try again"],
            }

    pending_with_inputs: list[dict[str, Any]] = []
    for t in pending:
        entry: dict[str, Any] = {"name": t["name"]}
        t_inputs = task_inputs.get(t["name"], [])
        if t_inputs:
            entry["inputs"] = t_inputs[0]
        pending_with_inputs.append(entry)

    msg = format_approval_message(pending_with_inputs)

    return {
        "final_response": msg,
        "_needs_approval": True,
        "_pending_approval_tools": pending_with_inputs,
        "_approval_requested_at": _time.time(),
        "_routing_decision": "finalize",
    }


# ============================================================================
# Node: Executor
# ============================================================================


async def executor_node(
    state: AgentState,
    tool_executor: ToolExecutor,
) -> dict[str, Any]:
    """Execute the DAG plan using the Concurrent Executor.

    Reads ``_optimized_graph`` or ``_execution_graph`` from the state
    (produced by the deterministic Compiler), converts PhysicalNodes
    to ExecutionTasks, and runs them via the ConcurrentExecutor.
    """
    from nexus.agent.planners.dag_planner import ExecutionTask, ExecutionWave

    graph_data = state.get("_optimized_graph") or state.get("_execution_graph")
    if graph_data is None or not isinstance(graph_data, dict):
        return {"_executor_results": {}, "_executor_failed": [], "_executor_all_success": False, "errors": ["No execution graph available"]}

    nodes = graph_data.get("nodes", {})
    waves = graph_data.get("waves", [])
    if not nodes or not waves:
        return {"_executor_results": {}, "_executor_failed": [], "_executor_all_success": False, "errors": ["No execution graph available"]}

    task_map = {}
    ref_to_id: dict[str, str] = {}
    collections = state.get("_collections", {})
    for nid, ndata in nodes.items():
        kind = ndata.get("kind", "")
        if kind == "map":
            body = ndata.get("body", {})
            symbolic_ref = ndata.get("symbolic_ref", "").replace("_map", "")
            if symbolic_ref:
                ref_to_id[symbolic_ref] = nid
            collection_key = ndata.get("iterate_over", "")
            items = collections.get(collection_key, [])
            if items:
                # Dynamic fan-out: one task per item
                for i, item in enumerate(items):
                    task_inputs = _expand_map_inputs(body.get("inputs", {}), item)
                    task_id = f"{nid}_item_{i}"
                    task_map[task_id] = ExecutionTask(
                        id=task_id,
                        tool_name=body.get("tool_name", body.get("capability", "unknown")),
                        endpoint_url=body.get("endpoint_url", ""),
                        http_method=body.get("http_method", "GET"),
                        inputs=task_inputs,
                        depends_on=ndata.get("depends_on", []),
                    )
                    # Register each item's task_id under its symbolic_ref for placeholder resolution
                    ref_to_id.get(symbolic_ref)
                    ref_to_id[f"{nid}_item_{i}"] = task_id
            else:
                # Fallback: no collection available — run once with body inputs
                task_map[nid] = ExecutionTask(
                    id=nid,
                    tool_name=body.get("tool_name", body.get("capability", "unknown")),
                    endpoint_url=body.get("endpoint_url", ""),
                    http_method=body.get("http_method", "GET"),
                    inputs=body.get("inputs", {}),
                    depends_on=ndata.get("depends_on", []),
                )
        elif kind == "tool":
            symbolic_ref = ndata.get("symbolic_ref", "")
            if symbolic_ref:
                ref_to_id[symbolic_ref] = nid
            task_map[nid] = ExecutionTask(
                id=nid,
                tool_name=ndata.get("tool_name", ndata.get("capability", "unknown")),
                endpoint_url=ndata.get("endpoint_url", ""),
                http_method=ndata.get("http_method", "GET"),
                inputs=ndata.get("inputs", {}),
                depends_on=ndata.get("depends_on", []),
            )

    wave_objects = [
        ExecutionWave(wave=idx, tasks=[task_map[tid] for tid in w if tid in task_map])
        for idx, w in enumerate(waves)
    ]

    available_tools = state.get("available_tools", [])
    tool_map = {t["name"]: t for t in available_tools if isinstance(t, dict) and t.get("name")}

    executor = ConcurrentExecutor(
        tool_executor=tool_executor,
        tool_map=tool_map,
        session_id=state.get("session_id", ""),
    )
    executor.set_ref_aliases(ref_to_id)
    _settings = get_settings()

    results = await executor.execute(
        tasks=list(task_map.values()),
        waves=wave_objects,
        max_concurrency=_settings.agent.adaptive_reflection.max_concurrent_tasks,
        per_tool_timeout=_settings.tools.execution_timeout_s,
        global_timeout=_settings.agent.global_execution_timeout_s,
    )

    # Validate tool results against output contracts from the registry
    from nexus.execution.contracts import validate_tool_result
    from nexus.registry.client import RegistryClient
    from nexus.db.base import async_session as _contract_session

    async with _contract_session() as _cs:
        _registry = RegistryClient(_cs)
        for _task_id, _outcome in results.by_task.items():
            if _outcome.status == "success":
                _cap = _outcome.tool_name
                _is_valid, _reason = await validate_tool_result(_cap, _outcome.data, _registry)
                if not _is_valid:
                    _outcome.status = "error"
                    _outcome.error = f"Output contract failed: {_reason}"
                    logger.warning("executor_node.contract_failed", tool=_cap, reason=_reason)

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

    # Emit WaveCompleted events
    session_id = state.get("session_id", "")
    for i, wave_dict in enumerate(results.by_wave):
        successes = sum(1 for r in wave_dict.values() if r.status == "success")
        failures = sum(1 for r in wave_dict.values() if r.status != "success")
        await emit_wave_completed(
            session_id=session_id,
            wave_index=i,
            tasks_succeeded=successes,
            tasks_failed=failures,
        )

    # Emit ExecutionFinished
    status = "success" if results.all_successful else "partial" if results.failed else "failed"
    await emit_execution_finished(
        session_id=session_id,
        status=status,
        total_cost=state.get("_cost_estimate", 0.0),
        total_latency_ms=state.get("_latency_estimate_ms", 0),
    )

    return {
        "tool_results": tool_results,
        "_executor_results": {
            k: {"data": v.data, "status": v.status}
            for k, v in results.by_task.items()
        },
        "_executor_failed": results.failed + results.timed_out,
        "_executor_all_success": results.all_successful,
        "_tool_executed_in_turn": True,
    }


# ============================================================================
# Node: Response
# ============================================================================


async def response_node(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Compose the final response from tool results or conversation history."""
    existing = state.get("final_response")
    if existing and (
        state.get("response_type") in ("greeting", "meta", "clarification")
        or state.get("_needs_approval")
    ):
        return {"final_response": existing, "_routing_decision": "finalize"}

    tool_results = state.get("tool_results", [])
    errors = state.get("errors", [])

    # DYNAMIC NATIVE CHAT: empty workflow + no tools → answer from conversation history
    workflow = state.get("_logical_workflow", {})
    nodes = workflow.get("nodes", []) if isinstance(workflow, dict) else []
    if not tool_results and not errors and len(nodes) == 0:
        messages = state.get("messages", [])
        chat_messages = [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in messages if isinstance(m, dict)
        ]
        try:
            response = await llm.complete(
                model=model, messages=chat_messages,
                temperature=0.7, max_tokens=500,
            )
            return {"final_response": response.content or "", "_routing_decision": "finalize", "response_type": "conversational"}
        except Exception as exc:
            logger.error("response_node.native_chat_failed", error=str(exc))
            return {"final_response": "I'm not sure how to respond.", "_routing_decision": "finalize", "response_type": "error"}

    if not tool_results and not errors:
        return {"final_response": "I processed your request.", "_routing_decision": "finalize", "response_type": "tool"}

    if errors and not tool_results:
        from nexus.agent.nodes.finalize import finalize as compose_response
        result = await compose_response(state, llm, model)
        result["response_type"] = "error"
        return result

    from nexus.agent.nodes.finalize import finalize as compose_response
    result = await compose_response(state, llm, model)
    result["response_type"] = "tool"
    return result


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


# ============================================================================
# Graph Builder — 13 nodes, 4 routing functions
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
    """Build and compile the 13-node deterministic workflow compiler graph.

    Args:
        llm_client: LLM client. Creates default if None.
        tool_selector: Dynamic tool discovery.
        tool_executor: Tool execution engine.
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

    # Lazy imports for new nodes
    from nexus.agent.nodes.semantic_parser_node import semantic_parser_node as _semantic_parser_node
    from nexus.agent.nodes.compiler_node import compiler_node as _compiler_node
    from nexus.agent.nodes.optimizer_node import optimizer_node as _optimizer_node
    from nexus.agent.nodes.estimator_node import estimator_node as _estimator_node
    from nexus.agent.nodes.validation_node import validation_node as _validation_node
    from nexus.agent.nodes.clarification_node import clarification_node as _clarification_node
    from nexus.agent.nodes.aggregator_node import aggregator_node as _aggregator_node
    from nexus.agent.nodes.reflection_node import reflection_node as _reflection_node
    from nexus.agent.nodes.memory_helper_node import memory_helper_node as _memory_helper_node

    # 13 production nodes
    graph.add_node("RouterNode", node(router_node, _llm, _model))
    graph.add_node("SemanticPlannerNode", node(_semantic_parser_node, _llm, _model))
    graph.add_node("CompilerNode", node(_compiler_node))
    graph.add_node("OptimizerNode", node(_optimizer_node))
    graph.add_node("EstimatorNode", node(_estimator_node))
    graph.add_node("ValidationNode", node(_validation_node))
    graph.add_node("ClarificationNode", node(_clarification_node))
    graph.add_node("ApprovalGateNode", node(approval_gate_node))
    graph.add_node("ExecutorNode", node(executor_node, _executor))
    graph.add_node("AggregatorNode", node(_aggregator_node))
    graph.add_node("ReflectionNode", node(_reflection_node))
    graph.add_node("ResponseNode", node(response_node, _llm, _model))
    graph.add_node("MemoryHelperNode", node(_memory_helper_node))

    graph.set_entry_point("RouterNode")

    # Router → SemanticPlanner (workflow) or Response (conversational/error)
    graph.add_conditional_edges(
        "RouterNode",
        route_after_router,
        {
            "SemanticPlannerNode": "SemanticPlannerNode",
            "ResponseNode": "ResponseNode",
        },
    )

    # Linear compilation pipeline: SemanticPlanner → Compiler → Optimizer → Estimator → Validation
    graph.add_edge("SemanticPlannerNode", "CompilerNode")
    graph.add_edge("CompilerNode", "OptimizerNode")
    graph.add_edge("OptimizerNode", "EstimatorNode")
    graph.add_edge("EstimatorNode", "ValidationNode")

    # Validation → Response (empty workflow), ApprovalGate (valid), or Clarification (invalid)
    graph.add_conditional_edges(
        "ValidationNode",
        route_after_validation,
        {
            "ResponseNode": "ResponseNode",
            "ApprovalGateNode": "ApprovalGateNode",
            "ClarificationNode": "ClarificationNode",
        },
    )
    graph.add_edge("ClarificationNode", END)

    # ApprovalGate → Executor (approved) or Response (rejected/no decision)
    graph.add_conditional_edges(
        "ApprovalGateNode",
        route_after_approval,
        {
            "ExecutorNode": "ExecutorNode",
            "ResponseNode": "ResponseNode",
        },
    )

    # Execution → Aggregation → Reflection
    graph.add_edge("ExecutorNode", "AggregatorNode")
    graph.add_edge("AggregatorNode", "ReflectionNode")

    # Reflection → Executor (retry sub-graph) or Response (finalize)
    graph.add_conditional_edges(
        "ReflectionNode",
        route_after_reflection,
        {
            "ExecutorNode": "ExecutorNode",
            "ResponseNode": "ResponseNode",
        },
    )

    # Response → Memory (persist) → END
    graph.add_edge("ResponseNode", "MemoryHelperNode")
    graph.add_edge("MemoryHelperNode", END)

    # Compile with checkpointer
    _cp = checkpointer
    if _cp is None:
        from langgraph.checkpoint.memory import MemorySaver

        _cp = MemorySaver()

    return graph.compile(checkpointer=_cp)
