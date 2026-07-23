"""plan_repair — rule-based plan fix after validation failures.

When ``plan_validator`` flags tasks with errors, this node applies
deterministic fixes:

1. Unknown tool → remove task from plan
2. Missing required field → fill from ``gathered_requirements`` or set to default
3. Cycle / bad dependency → correct the dependency
4. Depth limit → flatten the DAG

After max 2 repair attempts, routes to ``ask`` (user clarification).
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.plan_repair")

_MAX_REPAIR_RETRIES = 2


async def plan_repair(state: AgentState) -> dict[str, Any]:
    """Apply rule-based fixes to validation failures in the DAG plan.

    Reads ``_plan_validation_failures`` and ``dag_tasks`` from state.
    Returns corrected tasks or routes to ``ask`` if max retries exceeded.

    Returns:
        Dict with potentially updated ``dag_tasks``, ``_plan_repair_count``,
        and ``_routing_decision`` ("continue" for loop back to validator,
        "ask" if max retries).
    """
    failures: list[dict[str, Any]] = state.get("_plan_validation_failures", [])
    tasks: list[dict[str, Any]] = list(state.get("dag_tasks", []))
    tools: list[dict[str, Any]] = state.get("available_tools", [])
    tool_names: set[str] = {t["name"] for t in tools}
    gathered: dict[str, Any] = state.get("gathered_requirements", {})

    repair_count: int = state.get("_plan_repair_count", 0)
    if repair_count >= _MAX_REPAIR_RETRIES:
        logger.warning("plan_repair.max_retries", count=repair_count)
        return {
            "_plan_repair_count": repair_count + 1,
            "_routing_decision": "ask",
        }

    if not failures:
        return {"_plan_repair_count": repair_count + 1, "_routing_decision": "continue"}

    # Build repair index by task_id
    task_index: dict[str, dict[str, Any]] = {t["id"]: t for t in tasks if t.get("id")}
    tasks_removed: set[str] = set()

    for failure in failures:
        task_id = failure.get("task_id", "")
        field = failure.get("field", "")
        reason = failure.get("reason", "")
        severity = failure.get("severity", "warning")

        if severity != "error":
            continue

        task = task_index.get(task_id)
        if task is None or task_id in tasks_removed:
            continue

        # 1. Unknown tool → remove task
        if field == "tool_name" and "Unknown tool" in reason:
            logger.info("plan_repair.remove_unknown_tool", task_id=task_id, reason=reason)
            tasks_removed.add(task_id)
            continue

        # 2. Missing required field → try to fill from gathered
        if field.startswith("Missing required input"):
            field_name = field.split("'")[1] if "'" in field else field
            if field_name in gathered:
                task["inputs"][field_name] = gathered[field_name]
                logger.info("plan_repair.fill_from_gathered", task_id=task_id, field=field_name)
            else:
                # Set to None and let the executor handle it
                task["inputs"][field_name] = None
                logger.info("plan_repair.set_default", task_id=task_id, field=field_name)

        # 3. Cycle / bad dependency
        if field == "depends_on":
            if "depends on itself" in reason:
                task["depends_on"] = [d for d in task.get("depends_on", []) if d != task_id]
                logger.info("plan_repair.fix_self_dep", task_id=task_id)
            elif "not found" in reason:
                # Remove dependency on non-existent tasks
                all_ids = set(task_index.keys())
                task["depends_on"] = [d for d in task.get("depends_on", []) if d in all_ids]
                logger.info("plan_repair.fix_bad_dep", task_id=task_id)

    # Build corrected task list (minus removed tasks)
    corrected_tasks = [t for t in tasks if t.get("id") not in tasks_removed]

    if not corrected_tasks:
        logger.warning("plan_repair.all_tasks_removed")
        return {
            "dag_tasks": [],
            "_plan_repair_count": repair_count + 1,
            "_routing_decision": "ask",
        }

    logger.info(
        "plan_repair.completed",
        original=len(tasks),
        corrected=len(corrected_tasks),
        removed=len(tasks_removed),
        attempt=repair_count + 1,
    )
    return {
        "dag_tasks": corrected_tasks,
        "_plan_repair_count": repair_count + 1,
        "_routing_decision": "continue",
    }
