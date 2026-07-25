"""Plan Validator Node — pure Python pre-execution DAG validation.

Inserts between PlannerNode and ApprovalGateNode. Catches malformed
DAGs, missing prerequisites, and capability precondition failures
before they reach the executor or external APIs.

No LLM calls. Pure deterministic Python.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.plan_validator")


def _has_cycles(plan: dict[str, Any]) -> list[str]:
    """DFS-based cycle detection on the execution plan.

    Returns list of node IDs involved in cycles (empty if none).
    """
    waves = plan.get("waves", [])
    tasks_data = plan.get("dag_tasks", []) or []

    # Build adjacency list
    dag: dict[str, set[str]] = {}
    for w in waves:
        for t in w.get("tasks", []):
            tid = t.get("id", "")
            deps = t.get("depends_on", [])
            dag[tid] = set(deps)
            for d in deps:
                if d not in dag:
                    dag[d] = set()

    # DFS cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in dag}
    cycle_nodes: list[str] = []

    def dfs(node: str) -> None:
        color[node] = GRAY
        for child in dag.get(node, set()):
            if color.get(child) == GRAY:
                cycle_nodes.append(f"{node} → {child}")
            if color.get(child) == WHITE:
                dfs(child)
        color[node] = BLACK

    for node in dag:
        if color[node] == WHITE:
            dfs(node)

    return cycle_nodes


def _check_missing_prereqs(
    plan: dict[str, Any],
    tools: list[dict[str, Any]],
) -> list[str]:
    """Check that every tool's required inputs are satisfied by the plan.

    For each task, check its tool's input_schema.required fields.
    If a required field isn't in the task's inputs AND no prior task
    produces it as output, flag it.
    """
    waves = plan.get("waves", [])
    tasks_data = plan.get("dag_tasks", []) or []
    errors: list[str] = []

    # Build tool schema map
    tool_schemas: dict[str, dict] = {}
    for t in tools:
        tool_schemas[t.get("name", "")] = t.get("input_schema", {})

    # Build set of all output fields produced across all tasks
    all_outputs: set[str] = set()
    for w in waves:
        for t in w.get("tasks", []):
            tname = t.get("tool_name", "")
            tschema = tool_schemas.get(tname, {})
            out_props = tschema.get("properties", {}) if tschema else {}
            all_outputs.update(out_props.keys())

    # Check each task's required inputs
    for w in waves:
        for t in w.get("tasks", []):
            tname = t.get("tool_name", "")
            tschema = tool_schemas.get(tname, {})
            required = tschema.get("required", []) if isinstance(tschema, dict) else []
            task_inputs = t.get("inputs", {})
            for req in required:
                if req not in task_inputs and req not in all_outputs:
                    errors.append(f"Task '{t.get('id','')}' ({tname}): required input '{req}' not provided")

    return errors


async def plan_validator_node(state: AgentState) -> dict[str, Any]:
    """Validate the execution plan before it reaches the executor.

    Checks:
    1. DAG has at least one root node (no deadlock)
    2. No cycles in the DAG
    3. Every tool's required inputs are satisfied

    On validation failure, returns errors and routes to clarification.
    On success, returns empty dict (pass-through).
    """
    plan = state.get("_execution_plan", {})
    tools = state.get("available_tools", [])

    if not plan.get("waves"):
        return {}

    errors: list[str] = []

    # 1. Check for root nodes
    waves = plan.get("waves", [])
    all_tasks = [t for w in waves for t in w.get("tasks", [])]
    root_tasks = [t for t in all_tasks if not t.get("depends_on", [])]
    if not root_tasks:
        errors.append("DAG has no root node — all tasks have dependencies")

    # 2. Check for cycles
    cycles = _has_cycles(plan)
    if cycles:
        errors.append(f"DAG contains cycles: {cycles}")

    # 3. Check missing prerequisites
    prereq_errors = _check_missing_prereqs(plan, tools)
    errors.extend(prereq_errors)

    if errors:
        logger.warning("plan_validator.failed", errors=errors)
        return {
            "errors": errors,
            "_routing_decision": "clarify",
            "_needs_clarification": True,
        }

    logger.info("plan_validator.passed")
    return {}
