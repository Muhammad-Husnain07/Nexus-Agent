"""plan_validator — deterministic plan validation before execution.

Checks every DAG task against the tool registry for:
1. Tool existence — does the tool name match a known tool?
2. Input schema compliance — required fields present, types match?
3. DAG structure — no cycles, within depth/width limits?
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.plan_validator")


async def plan_validator(state: AgentState) -> dict[str, Any]:
    """Validate the DAG plan before tool execution.

    Reads ``dag_tasks`` and ``available_tools`` from state.  If a task
    fails validation, sets ``_plan_validation_failures`` with error details
    so the parent can route to ``plan_repair`` or fallback.

    Returns:
        Dict with ``_plan_validation_failures`` (list of error dicts) and
        ``_plan_valid`` (bool).  Empty list → plan is valid.
    """
    tasks: list[dict[str, Any]] = state.get("dag_tasks", [])
    tools: list[dict[str, Any]] = state.get("available_tools", [])
    tool_map: dict[str, dict[str, Any]] = {t["name"]: t for t in tools}
    failures: list[dict[str, Any]] = []

    # Track all task IDs for cycle detection
    task_ids: set[str] = set()
    for i, task in enumerate(tasks):
        tid = task.get("id", f"task_{i}")
        task_ids.add(tid)
        tool_name = task.get("tool_name")
        inputs = task.get("inputs", {})
        depends_on: list[str] = task.get("depends_on", [])

        # 1. Tool existence check
        if tool_name and tool_name not in tool_map:
            failures.append({
                "task_id": tid,
                "field": "tool_name",
                "reason": f"Unknown tool: '{tool_name}'. Not in registry.",
                "severity": "error",
            })
            continue

        if not tool_name and not task.get("approaches"):
            failures.append({
                "task_id": tid,
                "field": "tool_name",
                "reason": "Task has no tool_name and no approaches.",
                "severity": "error",
            })
            continue

        # 2. Input schema compliance (only if tool exists)
        if tool_name and tool_name in tool_map:
            schema = tool_map[tool_name].get("input_schema", {})
            if isinstance(schema, dict):
                required: list[str] = schema.get("required", [])
                for req_field in required:
                    if req_field not in inputs and req_field not in state.get("gathered_requirements", {}):
                        failures.append({
                            "task_id": tid,
                            "field": req_field,
                            "reason": f"Missing required input: '{req_field}'",
                            "severity": "warning",
                        })

                # Type hints (best-effort)
                props = schema.get("properties", {})
                for field_name, field_val in inputs.items():
                    prop = props.get(field_name, {})
                    expected_type = prop.get("type")
                    if expected_type and field_val is not None:
                        type_map = {
                            "string": str, "number": (int, float),
                            "integer": int, "boolean": bool,
                            "array": list, "object": dict,
                        }
                        py_type = type_map.get(expected_type)
                        if py_type and not isinstance(field_val, py_type):
                            failures.append({
                                "task_id": tid,
                                "field": field_name,
                                "reason": f"Expected type '{expected_type}', got {type(field_val).__name__}",
                                "severity": "warning",
                            })

    # 3. Cycle detection (simple: no self-referencing deps)
    for task in tasks:
        tid = task.get("id", "")
        for dep in task.get("depends_on", []):
            if dep == tid:
                failures.append({
                    "task_id": tid,
                    "field": "depends_on",
                    "reason": "Task depends on itself",
                    "severity": "error",
                })
            if dep not in task_ids:
                failures.append({
                    "task_id": tid,
                    "field": "depends_on",
                    "reason": f"Dependency '{dep}' not found in task list",
                    "severity": "error",
                })

    # 4. Depth/width limits
    max_depth = 5
    depths = _compute_depths(tasks)
    for tid, depth in depths.items():
        if depth > max_depth:
            failures.append({
                "task_id": tid,
                "field": "plan",
                "reason": f"Task depth {depth} exceeds max {max_depth}",
                "severity": "warning",
            })

    if failures:
        has_errors = any(f.get("severity") == "error" for f in failures)
        logger.warning(
            "plan_validator.failures",
            count=len(failures),
            has_errors=has_errors,
            tasks=len(tasks),
        )

    return {
        "_plan_validation_failures": failures,
        "_plan_valid": not any(f.get("severity") == "error" for f in failures),
    }


def _compute_depths(tasks: list[dict[str, Any]]) -> dict[str, int]:
    """Compute the dependency depth of each task via topological walk."""
    task_map: dict[str, dict[str, Any]] = {t["id"]: t for t in tasks}
    depths: dict[str, int] = {}

    def _depth(tid: str) -> int:
        if tid in depths:
            return depths[tid]
        task = task_map.get(tid)
        if not task or not task.get("depends_on"):
            depths[tid] = 0
            return 0
        max_d = max((_depth(d) for d in task["depends_on"] if d in task_map), default=0)
        depths[tid] = max_d + 1
        return depths[tid]

    for t in tasks:
        _depth(t["id"])
    return depths
