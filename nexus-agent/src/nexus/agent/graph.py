"""
Deterministic Workflow Compiler Graph — 19-node intent-first pipeline.

Nodes
=====
1.  **RouterNode** — Query classifier (heuristic + LLM fallback).
    Routes conversational → ResponseNode; workflow →
    InteractiveWorkflowNode; needs_requirements →
    RequirementCollectorNode; action → SemanticPlannerNode.
2.  **InteractiveWorkflowNode** — Template-driven workflow engine.
3.  **RequirementCollectorNode** — Iterative clarification loop (ready →
    SemanticPlannerNode).
4.  **SemanticPlannerNode** — Cache-first LLM → ``LogicalWorkflow``
    (intent-unit framing; instructor Literal enforcement; replans bypass
    the cache).
5.  **PlanValidatorNode** — Deterministic semantic validation: coverage,
    capability alignment (engine-score based), provenance, traceability,
    budget. Also the semantic cache gatekeeper (P2F).
6.  **CompilerNode** — Deterministic codegen: LogicalWorkflow →
    ExecutionGraph (+ RESOLVE producer-chain synthesis).
7.  **OptimizerNode** — PassManager fixpoint optimizer.
8.  **EstimatorNode** — Cost/latency estimation & budget check.
9.  **ValidationNode** — Structure/constraint validation.
10. **ApprovalGateNode** — Semantic-bound HITL approvals (operation hash).
11. **ApprovalCheckpointResumeNode** — Conversational approve/reject/
    cancel/modify/clarify.
12. **ExecutorNode** — Wave-based concurrent tool execution (authorized,
    idempotency-keyed, cancellable, sandboxed).
13. **AggregatorNode** — Pure Python ReduceNode execution (on success too).
14. **ValidatorNode** — Post-execution validation.
15. **RecoveryManagerNode** — Typed failure classification (retry / replan /
    partial / fail).
16. **ReflectionNode** — Structural diffing + bounded retry sub-graph.
17. **ReplanNode** — Shared-budget replan back to the planner.
18. **ResponseNode** — Data-incorporation + coverage guards; deterministic
    renderer floor.
19. **MemoryHelperNode** — Provenance-stamped memory persistence; never
    stores failed responses.

Pipeline
========
RouterNode
  |-> (conversational) ResponseNode -> MemoryHelperNode -> END
  |-> (workflow) InteractiveWorkflowNode
  |-> (needs_requirements) RequirementCollectorNode -> SemanticPlannerNode
  |-> (action) SemanticPlannerNode -> PlanValidatorNode
        |-> (refine) SemanticPlannerNode (bounded)
        |-> (require_more_info) RequirementCollectorNode
        |-> CompilerNode -> OptimizerNode -> EstimatorNode -> ValidationNode
              |-> ApprovalGateNode -> ExecutorNode
                    |-> AggregatorNode -> ValidatorNode
                          |-> RecoveryManagerNode
                                |-> (retry) ReflectionNode -> ExecutorNode
                                |-> (replan) ReplanNode -> SemanticPlannerNode
                                |-> (fail) ResponseNode
                    |-> ResponseNode -> MemoryHelperNode -> END
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph

from nexus.agent.budget import budget_from_state
from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
from nexus.agent.nodes.interactive_workflow_node import interactive_workflow_node as _interactive_workflow_node
from nexus.agent.nodes.replan_node import ReplanNode as _ReplanNode
from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.execution.events import emit_wave_completed, emit_execution_finished
from nexus.llm.client import LLMClient
from nexus.redis_client.pubsub import EventBus
from nexus.tools.executor import ToolExecutor

logger = structlog.get_logger("nexus.agent.graph")

import uuid  # noqa: E402
from datetime import datetime, timezone  # noqa: E402


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


def route_after_estimator(state: AgentState) -> str:
    """Route after estimation — always ValidationNode (DecompositionNode
    removed; ``_sub_workflows`` was never produced by any node, so the
    decomposition branch was unreachable)."""
    return "ValidationNode"


def route_after_plan_validator(state: AgentState) -> str:
    """Route based on the deterministic PlanValidatorReport.

    - require_more_info → RequirementCollectorNode (missing inputs)
    - refine/drop_op → SemanticPlannerNode (replan with errors). The NODE
      itself returns the abort patch (with errors attached) once the rounds
      cap is reached — the route must NOT cap early: a route-side intercept
      fires before the node's abort visit and drops the errors (the state
      would still carry the last refine patch).
    - abort → ResponseNode (honest explanation; never a silent dead end)
    - valid → CompilerNode
    """
    action = state.get("_plan_validator_action", "")
    rounds = int(state.get("_plan_validator_rounds", 0) or 0)

    if action == "abort":
        logger.warning("graph.route_plan_validator_abort", rounds=rounds)
        return "ResponseNode"
    if action == "require_more_info":
        logger.info("graph.route_plan_validator_requirements")
        return "RequirementCollectorNode"
    if action in ("refine", "drop_op"):
        logger.info("graph.route_plan_validator_replan", rounds=rounds)
        return "SemanticPlannerNode"
    return "CompilerNode"


def route_after_recovery(state: AgentState) -> str:
    """Route on the RecoveryManager decision (post self-heal).

    - retry → ReflectionNode (transient sub-graph retry — a strategy now)
    - replan → ReplanNode (structural invalidity → bounded replan)
    - fail → ResponseNode (explicit errors)
    """
    decision = state.get("_recovery_decision", {})
    action = decision.get("action", "fail") if isinstance(decision, dict) else "fail"
    if action == "retry":
        logger.info("graph.route_recovery_retry")
        return "ReflectionNode"
    if action == "replan":
        logger.info("graph.route_recovery_replan", reason=str(decision.get("reason", ""))[:80])
        return "ReplanNode"
    logger.warning("graph.route_recovery_fail", reason=str(decision.get("reason", ""))[:80])
    return "ResponseNode"


async def recovery_manager_node(state: AgentState) -> dict[str, Any]:
    """Classify post-execution failures into one recovery strategy.

    Deterministic (RecoveryManager): transient → retry; structural (unavailable
    op / schema changed / policy violation) → replan; exhausted → fail.
    """
    from nexus.agent.recovery import RecoveryManager

    tool_results = state.get("tool_results", []) or []
    failures: list[dict[str, Any]] = [
        dict(tr) for tr in tool_results
        if isinstance(tr, dict) and tr.get("status") != "success"
    ]
    # Post-execution validation failures (ValidatorNode tier-2/3) join the
    # typed failure set — a contract violation is a contract failure for the
    # recovery classifier, whether detected by the executor or the validator.
    validated_failed = state.get("_validation_failed") or []
    if validated_failed:
        known_ids = {str(f.get("task_id") or "") for f in failures}
        for tid in validated_failed:
            tid_s = str(tid)
            if tid_s and tid_s not in known_ids:
                failures.append({"task_id": tid_s, "status": "validation_error",
                                 "error": "post-execution validation failed",
                                 "tool_name": ""})
    replan_rounds = int(state.get("_replan_rounds", 0) or 0)
    try:
        max_replan = get_settings().compiler.max_replan_rounds
    except Exception:
        max_replan = 1
    try:
        max_retries = get_settings().agent.max_reflection_retries
    except Exception:
        max_retries = 0
    retries_used = int(state.get("_total_retry_count", 0) or 0)

    manager = RecoveryManager(max_replan_rounds=max_replan)
    decision = manager.decide(
        failures=failures,
        replan_rounds=replan_rounds,
        transient_retries_left=max(0, max_retries - retries_used),
        has_fallback_candidates=False,  # SelfHealing already ran
        approval_blocked=bool(state.get("_approval_denied_blocking", False)),
        budget_violated=state.get("_within_budget") is False,
        workflow_owned=bool(state.get("_active_workflow_id")),
    )
    logger.info(
        "graph.recovery_decision",
        action=decision.action.value,
        reason=decision.reason,
        failures=len(failures),
    )
    return {
        "_recovery_decision": decision.model_dump(),
        "_recovery_action": decision.action.value,
    }


def route_after_router(state: AgentState) -> str:
    """Route based on execution goals or active workflow state."""
    safety = state.get("_safety_result", {})
    if safety.get("action") == "reject":
        logger.warning("graph.safety_rejected", reason=safety.get("reason", ""))
        return "ResponseNode"

    # 0. Conversational approval checkpoint: an open decision is pending and
    # the user replied in-chat — classify and resume WITHOUT re-requesting.
    if state.get("_approval_pending") and not state.get("_bypass_workflow"):
        logger.info("graph.route_approval_checkpoint")
        return "ApprovalCheckpointResumeNode"

    # 1. If an active workflow exists, ALL user messages go to the workflow manager
    # UNLESS we are bypassing to handle an off-topic question
    if state.get("_active_workflow_id") and not state.get("_bypass_workflow"):
        logger.info("graph.route_active_workflow")
        return "InteractiveWorkflowNode"

    # 2. Otherwise, route based on the classified execution goals (with
    # legacy QueryType normalization for persisted checkpoints).
    from nexus.agent.goals import ExecutionGoals

    qtype = state.get("_query_type", "")
    goals = ExecutionGoals.from_legacy(qtype) if qtype else ExecutionGoals(goals=tuple())
    if state.get("_needs_requirements"):
        goals = ExecutionGoals(goals=goals.goals, needs_requirements=True)

    if goals.needs_requirements:
        logger.info("graph.route_requirements")
        return "RequirementCollectorNode"

    primary = goals.primary

    if primary.value == "conversation":
        return "ResponseNode"

    if primary.value == "information":
        # Knowledge queries go straight to the ResponseNode's conversational
        # path (KnowledgeAssistantNode merged away — the same direct-LLM
        # answer, one fewer node + checkpoint write).
        logger.info("graph.route_knowledge")
        return "ResponseNode"

    if primary.value == "workflow":
        if state.get("_bypass_workflow"):
            return "SemanticPlannerNode"
        logger.info("graph.route_workflow")
        return "InteractiveWorkflowNode"

    return "SemanticPlannerNode"


def route_after_validation(state: AgentState) -> str:
    """Route based on validation result.

    - needs clarification → RequirementCollectorNode (missing info)
    - errors → RequirementCollectorNode
    - empty workflow (0 nodes) → ResponseNode (conversational follow-up)
    - valid and has operations → ApprovalGateNode (proceed to HITL check)
    """
    # 1. Empty workflow (planner legitimately produced nothing) → conversational
    #    response. MUST be checked before clarification: a 0-node plan means
    #    there is nothing to clarify or execute — the turn ends with a
    #    ResponseNode instead of looping back into requirement collection.
    workflow = state.get("_logical_workflow", {})
    nodes = workflow.get("nodes", []) if isinstance(workflow, dict) else []
    if not workflow or len(nodes) == 0:
        logger.info("graph.route_empty_workflow")
        return "ResponseNode"

    # 2. Check clarification for a non-empty workflow (missing info)
    if state.get("_needs_clarification", False):
        return "RequirementCollectorNode"

    # 3. Then check for errors — uses the STRUCTURED validation result
    # (set by ValidationNode: {ready, missing, reason}) — no keyword lists.
    validation = state.get("_validation_result", {})
    if isinstance(validation, dict) and validation.get("ready") is False:
        return "RequirementCollectorNode"

    # 4. Check for operations in ir_stack
    ir_stack = state.get("_ir_stack", {})
    operations = ir_stack.get("operations", []) if isinstance(ir_stack, dict) else []
    if operations:
        return "ApprovalGateNode"

    if state.get("_ready_to_plan") is False:
        return "RequirementCollectorNode"

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


def route_after_checkpoint(state: AgentState) -> str:
    """Route after a conversational approval checkpoint reply.

    - resume with decision → ApprovalGateNode (consumes the decision)
    - replan (modification) → SemanticPlannerNode
    - finalize → ResponseNode
    """
    logger.info(
        "graph.route_after_checkpoint_debug",
        route_to_gate=state.get("_route_to_gate"),
        route_to_planner=state.get("_route_to_planner"),
        decision=state.get("_approval_decision"),
        pending=bool(state.get("_approval_pending")),
    )
    if state.get("_route_to_gate", False):
        logger.info("graph.route_checkpoint_to_gate")
        return "ApprovalGateNode"
    if state.get("_route_to_planner", False):
        logger.info("graph.route_checkpoint_to_planner")
        return "SemanticPlannerNode"
    if state.get("_routing_decision") == "replan":
        # Denial blocked a required dependency — planner replans the goal
        # without the denied tool (documented rule).
        logger.info("graph.route_checkpoint_replan")
        return "SemanticPlannerNode"
    return "ResponseNode"


def route_after_executor(state: AgentState) -> str:
    """Route after executor completes.

    - workflow step executed successfully → InteractiveWorkflowNode (same-turn
      resume: capture the result and finalize NOW, so the workflow never
      consumes the NEXT user message)
    - graph contains ReduceNodes → AggregatorNode (reduce operations are part
      of the normal graph contract — they must run on SUCCESS too, not only
      on the partial-failure path)
    - partial failure → AggregatorNode (normal pipeline)
    - all_success → ResponseNode (skip Aggregation/Reflection — Bug 10 fix)
    """
    if state.get("_workflow_next_action") == "execute_step" and state.get("_executor_all_success", True):
        logger.info("graph.route_executor_workflow_resume")
        return "InteractiveWorkflowNode"
    graph_data = state.get("_execution_graph") or {}
    nodes = graph_data.get("nodes") if isinstance(graph_data, dict) else None
    if isinstance(nodes, dict) and any(
        isinstance(n, dict) and n.get("kind") == "reduce"
        for n in nodes.values()
    ):
        logger.info("graph.route_executor_reduce_nodes")
        return "AggregatorNode"
    all_success = state.get("_executor_all_success", True)
    if all_success:
        logger.info("graph.route_executor_all_success")
        return "ResponseNode"
    return "AggregatorNode"


def route_after_reflection(state: AgentState) -> str:
    """Route based on reflection decision.

    - retry → ExecutorNode (retry only failed sub-graph)
    - finalize → ResponseNode
    """
    decision = state.get("_routing_decision", "finalize")
    if decision == "retry":
        return "ExecutorNode"
    return "ResponseNode"


def route_after_compiler(state: AgentState) -> str:
    """Route after CompilerNode — bypass the optimizer for tiny graphs.

    The pass-manager fixpoint plus its checkpoint write is pure overhead on
    small linear graphs (nothing to fuse/dedup/dead-code-eliminate): schema
    defaults and coercion are applied by the executor at call time, and the
    recovery ladder handles failures. Threshold is settings-driven
    (``compiler.optimizer_min_nodes``) — metadata, not hardcoded.
    """
    try:
        min_nodes = get_settings().compiler.optimizer_min_nodes
    except Exception:
        min_nodes = 3
    # Compile failure: route back to the planner (bounded by
    # ``_compile_retry_count``) or to the response once the bound is hit.
    if state.get("_route_to_planner", False):
        logger.info("graph.route_compiler_to_planner")
        return "SemanticPlannerNode"
    if state.get("_routing_decision") == "finalize":
        logger.info("graph.route_compiler_to_response")
        return "ResponseNode"
    graph_data = state.get("_execution_graph") or {}
    nodes = graph_data.get("nodes") if isinstance(graph_data, dict) else None
    # ExecutionBudget degradation: planning over budget → lightweight
    # pipeline (bypass the optimizer regardless of graph size).
    if state.get("_budget_exceeded"):
        logger.info("graph.bypass_optimizer_budget", reason=state.get("_budget_exceeded"))
        return "EstimatorNode"
    if isinstance(nodes, dict) and len(nodes) <= min_nodes:
        logger.info("graph.bypass_optimizer", nodes=len(nodes), min_nodes=min_nodes)
        return "EstimatorNode"
    return "OptimizerNode"


def route_after_requirement_collector(state: AgentState) -> str:
    """Route after gathering requirements.

    - ready → SemanticPlannerNode (proceed to compilation)
    - else → END (graph ends — user needs to reply to the question)
    """
    ready = state.get("_ready_to_plan", False) or state.get("_route_to_planner", False)
    if ready:
        return "SemanticPlannerNode"
    return END


def route_after_workflow(state: AgentState) -> str:
    """Route after interactive workflow step.

    - finalize → ResponseNode (workflow complete or waiting for user input)
    - route_to_compiler → CompilerNode (execute next step, bypassing planner)
    - route_to_planner → SemanticPlannerNode (HYBRID: dynamic step planning)
    - route_to_router → RouterNode (handle off-topic question)
    - else → END
    """
    if state.get("_routing_decision") == "finalize":
        return "ResponseNode"
    if state.get("_route_to_compiler", False):
        return "CompilerNode"
    if state.get("_route_to_planner", False):
        logger.info("graph.route_workflow_to_planner")
        return "SemanticPlannerNode"
    if state.get("_route_to_router", False):
        return "RouterNode"
    return END


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


def _rebuild_waves(nodes: dict[str, Any]) -> list[list[str]]:
    """Rebuild topological waves from dependency edges (Kahn's algorithm).

    Used when a graph carries no precomputed ``waves`` (e.g. the retry
    sub-graph emitted by ReflectionNode). Nodes with unresolved dependency
    cycles are dropped from the schedule rather than deadlocking execution.

    Args:
        nodes: ``{node_id: node_dict}`` mapping with ``depends_on`` edges.

    Returns:
        A list of waves; each wave is a list of node ids executable in parallel.
    """
    remaining = {nid: set(nd.get("depends_on", []) or []) for nid, nd in nodes.items()}
    # Keep only dependencies that actually exist in the sub-graph — patched
    # nodes reference the ORIGINAL graph's ids for out-of-subgraph deps,
    # which are already satisfied by the parent execution.
    for nid in remaining:
        remaining[nid] = {d for d in remaining[nid] if d in nodes}

    waves: list[list[str]] = []
    while remaining:
        ready = [nid for nid, deps in remaining.items() if not deps]
        if not ready:
            # Cycle (or orphaned refs) — deterministically break it by
            # promoting the lowest-id node; the executor reports missing
            # results for its unresolvable dependency.
            victim = sorted(remaining.keys())[0]
            remaining.pop(victim, None)
            for deps in remaining.values():
                deps.discard(victim)
            waves.append([victim])
            continue
        waves.append(sorted(ready))
        for nid in ready:
            remaining.pop(nid, None)
        for deps in remaining.values():
            deps.difference_update(ready)
    return waves


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
    graph_data = state.get("_execution_graph")

    if not graph_data:
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

    # Query DB for risk_level/requires_approval only for tools in the plan
    from nexus.db.base import async_session as _approval_db
    from nexus.db.models.tool import Tool
    from sqlalchemy import select

    approval_tool_list: list[dict[str, Any]] = []
    async with _approval_db() as session:
        result = await session.execute(
            select(Tool).where(Tool.name.in_(tool_names))
        )
        tools_db = result.scalars().all()
        for t in tools_db:
            approval_tool_list.append({
                "name": t.name,
                "risk_level": t.risk_level,
                "requires_approval": t.requires_approval,
            })

    pending = check_plan_approval(tool_names, approval_tool_list)
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


def _tool_meta_to_read_dict(t: Any) -> dict[str, Any]:
    """FK-REPAIR (P2-E): the canonical registry-tool metadata dict.

    Builds the complete ToolRead-valid metadata for a registry ``Tool`` row.
    The ``id`` is the REGISTRY id — the canonical identity that
    ``tool_execution.tool_id`` may reference. Compiled-graph/synthetic ids
    (the zero-UUID stub) must NEVER reach the DB foreign key; this dict
    carries the registry id so ToolRead validation succeeds and the
    persisted row references the registry. ``version``/``created_at``/
    ``updated_at`` are ToolRead-required and were previously omitted
    (validation fell back to the stub for every registered tool).
    """
    from datetime import datetime as _dt

    _now = _dt.now().isoformat()
    return {
        "name": t.name,
        "id": str(t.id),
        "description": t.description or "",
        "purpose": t.purpose or "",
        "tool_type": "http_api",
        "endpoint_url": t.endpoint_url or "",
        "http_method": t.http_method or "GET",
        "auth_type": t.auth_type or "none",
        "auth_ref": t.auth_ref or "",
        "input_schema": t.input_schema or {},
        "output_schema": t.output_schema or {},
        "validation_rules": t.validation_rules or {},
        "examples": t.examples or [],
        "tags": t.tags or [],
        "category": t.category or "general",
        "risk_level": t.risk_level or "low",
        "requires_approval": t.requires_approval or False,
        "enabled": t.enabled if t.enabled is not None else True,
        "rate_limit_per_minute": t.rate_limit_per_minute,
        "keywords": t.keywords,
        "aliases": t.aliases,
        "idempotent": t.idempotent if t.idempotent is not None else False,
        "cacheable": t.cacheable if t.cacheable is not None else True,
        "mcp_server_url": t.mcp_server_url or "",
        "version": t.version if t.version is not None else 1,
        "created_at": _now,
        "updated_at": _now,
    }


async def executor_node(
    state: AgentState,
    tool_executor: ToolExecutor,
) -> dict[str, Any]:
    """Execute the DAG plan using the Concurrent Executor.

    Reads ``_execution_graph`` from the state
    (produced by the deterministic Compiler), converts PhysicalNodes
    to ExecutionTasks, and runs them via the ConcurrentExecutor.
    """
    from nexus.agent.planners.dag_planner import ExecutionTask, ExecutionWave

    # Retry sub-graph takes precedence: ReflectionNode emits `_graph_patch`
    # with ONLY the failed nodes + dependents, so a retry re-executes just
    # the affected sub-graph instead of the entire workflow (no duplicate
    # side effects on already-succeeded tools).
    graph_data = state.get("_graph_patch") or state.get("_execution_graph")
    if graph_data is None or not isinstance(graph_data, dict):
        return {"_executor_failed": [], "_executor_all_success": False, "errors": ["No execution graph available"]}

    nodes = graph_data.get("nodes", {})
    waves = graph_data.get("waves", [])
    if not nodes:
        return {"_executor_failed": [], "_executor_all_success": False, "errors": ["No execution graph available"]}

    # Background handoff: when the estimator marked the plan for background
    # execution (estimated latency >= threshold), enqueue the WHOLE run via
    # an immutable ExecutionRequest — the worker owns the full graph
    # (checkpoints/artifacts/approvals/retries/recovery in one runtime).
    if state.get("_background_execution"):
        import uuid as _uuid

        from nexus.agent.prompts.logical_planner import PLANNER_VERSION
        from nexus.capabilities.resolution_engine import (
            RESOLVER_VERSION,
            registry_version,
        )
        from nexus.compiler.ir_models import COMPILER_VERSION
        from nexus.execution.lifecycle import ExecutionRequest
        from nexus.tasks.registry import TaskRegistry

        session_id = str(state.get("session_id", ""))
        last_message = ""
        for m in reversed(state.get("messages", []) or []):
            content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
            role = m.get("role", "") if isinstance(m, dict) else getattr(m, "role", "")
            if role == "user":
                last_message = str(content)
                break
        request = ExecutionRequest(
            execution_id=str(_uuid.uuid4()),
            session_id=session_id,
            thread_id=session_id or None,
            message=last_message,
            execution_plan_version=1,
            resolver_version=RESOLVER_VERSION,
            planner_version=PLANNER_VERSION,
            compiler_version=COMPILER_VERSION,
            registry_version=registry_version(),
        )
        try:
            from nexus.providers.queue.redis_streams import RedisStreamsQueue
            from nexus.tasks.registry import TaskRegistry

            task = await TaskRegistry().create(
                task_type="workflow_run",
                payload=request.model_dump(),
                session_id=session_id or None,
            )
            task_id = str(task["id"])
            # Enqueue for the worker (same path as the tasks API — a task
            # row without a queue entry never gets claimed).
            queue = RedisStreamsQueue()
            await queue.enqueue(task_id, request.model_dump())
        except Exception as _bg_exc:
            logger.warning("executor_node.background_enqueue_failed", error=str(_bg_exc)[:200])
            return {
                "_executor_failed": [],
                "_executor_all_success": False,
                "errors": [f"Background enqueue failed: {str(_bg_exc)[:120]}"],
            }
        logger.info("executor_node.background_enqueued", task_id=task_id, execution_id=request.execution_id)
        return {
            "_background_task_id": task_id,
            "response_type": "background",
            "final_response": (
                f"I've started this in the background (task {task_id[:8]}). "
                "You can check its progress on the Tasks page."
            ),
            "_executor_failed": [],
            "_executor_all_success": True,
        }

    # A patched sub-graph ships with empty waves — rebuild them from the
    # dependency edges (Kahn-style) so the executor schedules correctly.
    if not waves:
        waves = _rebuild_waves(nodes)

    task_map = {}
    ref_to_id: dict[str, str] = {}
    # Map of map-node id → list of fan-out task ids (for wave expansion)
    fan_out: dict[str, list[str]] = {}
    # P1-D: the LogicalWorkflow's declared collections (MapNode iteration
    # sources — the planner's map-collapse pass) feed the executor's fan-out.
    collections = state.get("_collections", {})
    if not collections:
        _wf = state.get("_logical_workflow") or {}
        if isinstance(_wf, dict) and _wf.get("collections"):
            collections = _wf.get("collections") or {}
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
                item_ids: list[str] = []
                for i, item in enumerate(items):
                    task_inputs = _expand_map_inputs(body.get("inputs", {}), item)
                    task_id = f"{nid}_item_{i}"
                    item_ids.append(task_id)
                    task_map[task_id] = ExecutionTask(
                        id=task_id,
                        tool_name=body.get("tool_name", body.get("capability", "unknown")),
                        endpoint_url=body.get("endpoint_url", ""),
                        http_method=body.get("http_method", "GET"),
                        inputs=task_inputs,
                        depends_on=ndata.get("depends_on", []),
                        candidate_endpoints=body.get("candidate_endpoints", []),
                    )
                    # Register each item's task_id under its symbolic_ref for placeholder resolution
                    ref_to_id[f"{nid}_item_{i}"] = task_id
                if symbolic_ref:
                    # The symbolic ref resolves to ALL item tasks (downstream
                    # consumers receive the item result list via aggregation).
                    ref_to_id[symbolic_ref] = ",".join(item_ids)
                fan_out[nid] = item_ids
            else:
                # Fallback: no collection available — run once with body inputs
                task_map[nid] = ExecutionTask(
                id=nid,
                tool_name=body.get("tool_name", body.get("capability", "unknown")),
                endpoint_url=body.get("endpoint_url", ""),
                http_method=body.get("http_method", "GET"),
                inputs=body.get("inputs", {}),
                depends_on=ndata.get("depends_on", []),
                candidate_endpoints=body.get("candidate_endpoints", []),
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
                candidate_endpoints=ndata.get("candidate_endpoints", []),
            )
        elif kind == "conditional":
            # Conditional gate — evaluated by the executor between waves.
            # The gate itself executes no tool; its branches are pruned based
            # on the evaluated condition against accumulated results.
            task_map[nid] = ExecutionTask(
                id=nid,
                tool_name="__conditional__",
                kind="conditional",
                condition=ndata.get("condition", ""),
                branch_true=list(ndata.get("branch_true", []) or []),
                branch_false=list(ndata.get("branch_false", []) or []),
                depends_on=ndata.get("depends_on", []),
            )

    def _expand_wave(w: list[str]) -> list[str]:
        """Expand a wave so map fan-out tasks replace their map node id."""
        expanded: list[str] = []
        for tid in w:
            if tid in fan_out:
                expanded.extend(fan_out[tid])
            elif tid in task_map:
                expanded.append(tid)
        return expanded

    wave_objects = [
        ExecutionWave(wave=idx, tasks=[task_map[tid] for tid in _expand_wave(w) if tid in task_map])
        for idx, w in enumerate(waves)
    ]

    # Build tool_map from GlobalContext O(1) capability_providers, filtered by graph nodes
    from nexus.context.global_context import get_global_context
    gc = get_global_context()

    # Collect only the tool names needed for this execution
    required_tool_names: set[str] = set()
    for nid, ndata in nodes.items():
        tool_name = ndata.get("tool_name") or ndata.get("capability")
        if tool_name and tool_name != "__conditional__":
            required_tool_names.add(tool_name)
        # Handle map nodes
        if ndata.get("kind") == "map":
            body = ndata.get("body", {})
            tool_name = body.get("tool_name") or body.get("capability")
            if tool_name:
                required_tool_names.add(tool_name)

    # Load full Tool metadata from the DB registry so ToolRead validation
    # succeeds at execution time (previously the minimal provider dict failed
    # validation and every tool fell back to an empty-URL stub).
    _tool_meta: dict[str, dict[str, Any]] = {}
    try:
        from nexus.db.base import async_session as _tool_db
        from nexus.db.models.tool import Tool
        from sqlalchemy import select as _select

        async with _tool_db() as _sess:
            _result = await _sess.execute(
                _select(Tool).where(Tool.name.in_(list(required_tool_names)))
            )
            for t in _result.scalars().all():
                _tool_meta[t.name] = _tool_meta_to_read_dict(t)
    except Exception as _exc:
        logger.warning("executor_node.tool_meta_load_failed", error=str(_exc))

    tool_map: dict[str, dict[str, Any]] = {}
    for tool_name in required_tool_names:
        providers = gc.get_capability_providers(tool_name)
        base = dict(_tool_meta.get(tool_name, {}))
        base.setdefault("name", tool_name)
        base.setdefault("auth_type", "none")
        base.setdefault("auth_ref", "")
        base.setdefault("endpoint_url", "")
        base.setdefault("http_method", "GET")
        if providers:
            # Take the first (highest-scored) provider for base auth metadata
            prov = providers[0]
            base.setdefault("endpoint_url", prov.get("url", ""))
            base.setdefault("http_method", prov.get("http_method", "GET"))
            base.setdefault("auth_type", prov.get("auth_type", "none"))
            base.setdefault("auth_ref", prov.get("auth_ref", ""))
        tool_map[tool_name] = base

    executor = ConcurrentExecutor(
        tool_executor=tool_executor,
        tool_map=tool_map,
        session_id=state.get("session_id", ""),
        budget=budget_from_state(state),
        user_roles=list((state.get("user_context") or {}).get("roles") or []),
        # P2-C: the parent invocation identity — stamped onto every tool
        # execution row, ledger claim and artifact-cache entry.
        agent_run_id=state.get("_invocation_id"),
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

    tool_results = []
    for task_id, outcome in results.by_task.items():
        tool_results.append({
            "tool_name": outcome.tool_name,
            "status": outcome.status,
            "data": outcome.data,
            "error": outcome.error,
            "task_id": outcome.task_id,
            "duration_ms": outcome.duration_ms,
            "retries": getattr(outcome, "retries", 0) or 0,
            "cached": bool(getattr(outcome, "cached", False)),
        })

    # Immutable, append-only execution-event trail (Phase 2): every task
    # lifecycle transition, bounded (last N), persisted in the turn's state
    # for replay/debugging. Events reference the execution/task id.
    from nexus.events.models import ExecutionEvent

    _MAX_EVENTS = 50
    prior_events: list[dict] = list(state.get("_execution_events") or [])
    _exec_events: list[dict] = []
    _now_iso = datetime.now(timezone.utc).isoformat()

    def _ev(event_type: str, execution_id: str, tool_name: str = "",
            status: str = "", duration: float = 0.0, error: str = "",
            artifact_id: str = "") -> None:
        _exec_events.append(ExecutionEvent(
            event_id=str(uuid.uuid4()),
            timestamp=_now_iso,
            type=event_type,
            execution_id=execution_id,
            tool_name=tool_name,
            status=status,
            duration_ms=duration,
            error=error,
            artifact_id=artifact_id,
        ).model_dump())

    for tid, outcome in results.by_task.items():
        if outcome.status == "skipped":
            _ev("TASK_SKIPPED", outcome.task_id, outcome.tool_name, status="skipped")
        elif bool(getattr(outcome, "cached", False)):
            _ev("TASK_CACHED", outcome.task_id, outcome.tool_name,
                status=outcome.status, duration=outcome.duration_ms)
        elif outcome.status == "success":
            _ev("TASK_COMPLETED", outcome.task_id, outcome.tool_name,
                status="success", duration=outcome.duration_ms)
        else:
            _ev("TASK_FAILED", outcome.task_id, outcome.tool_name,
                status=outcome.status, duration=outcome.duration_ms,
                error=str(outcome.error or "")[:300])
    _ev("GRAPH_COMPLETED", "graph",
        status="success" if results.all_successful else "partial" if results.failed else "failed")
    combined = prior_events + _exec_events
    execution_events = combined[-_MAX_EVENTS:]
    session_id = state.get("session_id", "")

    # EXECUTION→ARTIFACT INVARIANT (Step 4): every SUCCESS outcome must have
    # a registered artifact in the ArtifactGraph (by execution id). A missing
    # artifact means the execution→response handoff broke — detected here,
    # before response synthesis, and surfaced explicitly (never silently).
    try:
        from nexus.artifacts.graph import get_artifact_graph

        artifact_graph = get_artifact_graph(str(session_id))
        registered_ids = {
            a.execution_id for a in artifact_graph.all()
            if getattr(a, "execution_id", None)
        }
        missing_artifacts = [
            outcome.tool_name
            for outcome in results.by_task.values()
            if outcome.status == "success" and outcome.task_id not in registered_ids
        ]
        if missing_artifacts:
            logger.error(
                "executor_node.missing_artifacts",
                tools=missing_artifacts,
                session_id=str(session_id),
            )
            tool_results.append({
                "tool_name": "artifact_registry",
                "status": "error",
                "data": None,
                "error": f"no artifact registered for successful tool(s): {sorted(set(missing_artifacts))}",
                "task_id": "artifact_invariant",
                "duration_ms": 0,
                "retries": 0,
                "cached": False,
            })
    except Exception as _inv_exc:
        logger.warning(
            "executor_node.artifact_invariant_check_failed",
            error=str(_inv_exc)[:200],
        )

    # Emit WaveCompleted events (skipped conditional-branch tasks are not
    # failures — exclude them from the failure count). P1-A: per-wave
    # durations ride the event for critical-path accounting.
    for i, wave_dict in enumerate(results.by_wave):
        successes = sum(1 for r in wave_dict.values() if r.status == "success")
        failures = sum(1 for r in wave_dict.values() if r.status not in ("success", "skipped"))
        await emit_wave_completed(
            session_id=session_id,
            wave_index=i,
            tasks_succeeded=successes,
            tasks_failed=failures,
            duration_ms=(
                results.wave_durations_ms[i]
                if i < len(results.wave_durations_ms) else 0.0
            ),
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
        "_executor_failed": results.failed + results.timed_out,
        "_executor_all_success": results.all_successful,
        "_tool_executed_in_turn": True,
        "_execution_events": execution_events,
        # The executor's consumed tool-call ledger flows back so the
        # ReasoningBudget stays accurate across subsystems/observability.
        "_invocation_budget": executor._budget.to_dict()
        if getattr(executor, "_budget", None) is not None else {},
    }


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
    tool_executor: ToolExecutor | None = None,
    event_bus: EventBus | None = None,
    model: str | None = None,
    session_factory: Callable[[], Any] | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> StateGraph:
    """Build and compile the 13-node deterministic workflow compiler graph.

    Args:
        llm_client: LLM client. Creates default if None.
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

    # Build the 4 compiler subgraphs (each registers its nodes into the parent graph)
    from nexus.agent.subgraphs.frontend import build_frontend
    from nexus.agent.subgraphs.middle_end import build_middle_end
    from nexus.agent.subgraphs.backend import build_backend
    from nexus.agent.subgraphs.codegen import build_codegen

    build_frontend(graph, _llm, _model)
    build_middle_end(graph, _llm, _model)
    build_backend(graph, _executor)
    build_codegen(graph, _llm, _model)

    # Register InteractiveWorkflowNode directly (not in a subgraph)
    graph.add_node("InteractiveWorkflowNode", node(_interactive_workflow_node, _llm, _model))

    # Deterministic PlanValidatorNode (between planner and compiler)
    from nexus.agent.nodes.plan_validator_node import PlanValidatorNode

    try:
        _budget_cap = float(settings.compiler.max_budget_usd)
    except Exception:
        _budget_cap = None
    graph.add_node("PlanValidatorNode", PlanValidatorNode(budget_cap_usd=_budget_cap))

    # Recovery manager + replan (post self-heal decision point)
    graph.add_node("RecoveryManagerNode", recovery_manager_node)
    graph.add_node("ReplanNode", node(_ReplanNode()))

    # Conversational approval checkpoint resume node
    from nexus.agent.nodes.approval_checkpoint_resume_node import (
        approval_checkpoint_resume_node as _approval_checkpoint_resume_node,
    )
    graph.add_node(
        "ApprovalCheckpointResumeNode",
        node(_approval_checkpoint_resume_node, _llm, _model),
    )

    graph.set_entry_point("RouterNode")

    # Router → InteractiveWorkflowNode or Frontend (or directly to Codegen)
    graph.add_conditional_edges(
        "RouterNode",
        route_after_router,
        {
            "InteractiveWorkflowNode": "InteractiveWorkflowNode",
            "ApprovalCheckpointResumeNode": "ApprovalCheckpointResumeNode",
            "SemanticPlannerNode": "SemanticPlannerNode",
            "ResponseNode": "ResponseNode",
            "RequirementCollectorNode": "RequirementCollectorNode",
        },
    )

    # ApprovalCheckpointResumeNode → gate (decision), planner (modify), or response
    graph.add_conditional_edges(
        "ApprovalCheckpointResumeNode",
        route_after_checkpoint,
        {
            "ApprovalGateNode": "ApprovalGateNode",
            "SemanticPlannerNode": "SemanticPlannerNode",
            "ResponseNode": "ResponseNode",
        },
    )

    # InteractiveWorkflowNode → CompilerNode, SemanticPlannerNode (dynamic
    # step hybrid), RouterNode, or ResponseNode
    graph.add_conditional_edges(
        "InteractiveWorkflowNode",
        route_after_workflow,
        {
            "CompilerNode": "CompilerNode",
            "SemanticPlannerNode": "SemanticPlannerNode",
            "RouterNode": "RouterNode",
            "ResponseNode": "ResponseNode",
            END: END,
        },
    )

    # Frontend → Plan Validator → Middle-End (linear compilation pipeline)
    graph.add_edge("SemanticPlannerNode", "PlanValidatorNode")
    graph.add_conditional_edges(
        "PlanValidatorNode",
        route_after_plan_validator,
        {
            "CompilerNode": "CompilerNode",
            "RequirementCollectorNode": "RequirementCollectorNode",
            "SemanticPlannerNode": "SemanticPlannerNode",
            "ResponseNode": "ResponseNode",
            END: END,
        },
    )
    graph.add_conditional_edges(
        "CompilerNode",
        route_after_compiler,
        {
            "OptimizerNode": "OptimizerNode",
            "EstimatorNode": "EstimatorNode",
            "SemanticPlannerNode": "SemanticPlannerNode",
            "ResponseNode": "ResponseNode",
        },
    )
    graph.add_edge("OptimizerNode", "EstimatorNode")

    # Estimator → Validation (DecompositionNode removed — unreachable branch)
    graph.add_edge("EstimatorNode", "ValidationNode")

    # Validation → Backend (ApprovalGate/Executor) or Codegen (empty workflow) or back to Frontend
    graph.add_conditional_edges(
        "ValidationNode",
        route_after_validation,
        {
            "ApprovalGateNode": "ApprovalGateNode",
            "ResponseNode": "ResponseNode",
            "RequirementCollectorNode": "RequirementCollectorNode",
        },
    )

    # RequirementCollector → END or back to SemanticPlanner
    graph.add_conditional_edges(
        "RequirementCollectorNode",
        route_after_requirement_collector,
        {
            "SemanticPlannerNode": "SemanticPlannerNode",
            END: END,
        },
    )

    # Backend internal: ApprovalGate → Executor (or Codegen if rejected)
    graph.add_conditional_edges(
        "ApprovalGateNode",
        route_after_approval,
        {
            "ExecutorNode": "ExecutorNode",
            "ResponseNode": "ResponseNode",
        },
    )

    # Execution → Codegen (all_success) or Aggregation (partial failure)
    # or back to the workflow node (same-turn workflow resume/finalize)
    graph.add_conditional_edges(
        "ExecutorNode",
        route_after_executor,
        {
            "AggregatorNode": "AggregatorNode",
            "ResponseNode": "ResponseNode",
            "InteractiveWorkflowNode": "InteractiveWorkflowNode",
        },
    )

    # Aggregation → Validation → Recovery (linear pipeline; SelfHealingNode
    # removed — its patch had no consumers, endpoint fallback lives in the
    # executor)
    graph.add_edge("AggregatorNode", "ValidatorNode")
    graph.add_edge("ValidatorNode", "RecoveryManagerNode")
    graph.add_conditional_edges(
        "RecoveryManagerNode",
        route_after_recovery,
        {
            "ReflectionNode": "ReflectionNode",
            "ReplanNode": "ReplanNode",
            "ResponseNode": "ResponseNode",
        },
    )
    graph.add_edge("ReplanNode", "SemanticPlannerNode")

    # Reflection → Executor (retry) or Codegen (finalize)
    graph.add_conditional_edges(
        "ReflectionNode",
        route_after_reflection,
        {
            "ExecutorNode": "ExecutorNode",
            "ResponseNode": "ResponseNode",
        },
    )

    # Codegen: Response → Memory → END
    graph.add_edge("ResponseNode", "MemoryHelperNode")
    graph.add_edge("MemoryHelperNode", END)

    # Compile with checkpointer
    _cp = checkpointer
    if _cp is None:
        from langgraph.checkpoint.memory import MemorySaver

        _cp = MemorySaver()

    return graph.compile(checkpointer=_cp)
