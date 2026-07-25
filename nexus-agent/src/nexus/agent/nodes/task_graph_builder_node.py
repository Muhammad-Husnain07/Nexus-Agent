"""Task Graph Builder — converts a resolved capability chain into a topological DAG.

Stage 2 of the 3-stage planner pipeline.

Takes the capability chain from ResolutionNode and builds an ExecutionGraph
with proper task dependencies based on each capability's consumes/produces.

Pure Python — no LLM calls.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.task_graph_builder")


async def task_graph_builder_node(state: AgentState) -> dict[str, Any]:
    """Convert a resolved capability chain into an executable DAG.

    Reads ``_resolution_chain`` from state (set by ResolutionNode).
    Builds ``_execution_plan`` and ``dag_tasks`` compatible with the
    existing ExecutorNode.

    If no resolution chain exists, returns empty (PlannerNode fallback).
    """
    chain = state.get("_resolution_chain", [])
    if not chain:
        logger.info("task_graph_builder.no_chain")
        return {}

    # Get capability details
    try:
        from nexus.agent.registry.capability_registry import get_capability_registry
        cap_reg = get_capability_registry()
    except Exception:
        return {}

    capabilities = {}
    for cap_name in chain:
        cap = cap_reg.get_capability(cap_name)
        if cap:
            capabilities[cap_name] = cap

    if not capabilities:
        logger.info("task_graph_builder.no_capabilities")
        return {}

    # Build tasks from capability chain, respecting consumes/produces deps
    tasks: list[dict[str, Any]] = []
    dependency_map: dict[str, list[str]] = {}

    for i, cap_name in enumerate(chain):
        cap = capabilities[cap_name]
        task_id = f"task_{i + 1}"

        # Determine dependencies: this task depends on tasks whose
        # capabilities produced artifacts that this one consumes
        depends_on: list[str] = []
        for j in range(i):
            prev_cap = capabilities.get(chain[j])
            if prev_cap and set(prev_cap.produces) & set(cap.consumes):
                depends_on.append(f"task_{j + 1}")

        # Pick the first tool as default (Optimizer will refine this)
        tool_name = cap.tool_names[0] if cap.tool_names else cap_name

        tasks.append({
            "id": task_id,
            "tool_name": tool_name,
            "inputs": {},
            "description": cap.description,
            "depends_on": depends_on,
        })
        dependency_map[task_id] = depends_on

    # Build waves via topological sort
    waves = _build_waves(tasks)
    tool_names = list({t["tool_name"] for t in tasks})
    all_deps = [(d[0], t["id"]) for t in tasks for d in [("", "")] if t["depends_on"]]

    logger.info(
        "task_graph_builder.built",
        task_count=len(tasks),
        wave_count=len(waves),
        tools=tool_names,
    )

    return {
        "_execution_plan": {
            "waves": waves,
            "tool_names": tool_names,
            "dependencies": [(a, b) for t in tasks for a in t["depends_on"] for b in [t["id"]]],
        },
        "dag_tasks": tasks,
    }


def _build_waves(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Simple topological sort: root tasks go in wave 0, then dependents."""
    in_degree: dict[str, int] = {}
    children: dict[str, list[str]] = {}
    task_map = {t["id"]: t for t in tasks}

    for t in tasks:
        in_degree[t["id"]] = len(t.get("depends_on", []))
        for dep in t.get("depends_on", []):
            children.setdefault(dep, []).append(t["id"])

    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    waves = []
    wave_idx = 0

    while queue:
        wave_tasks = [task_map[q] for q in queue]
        wave_tasks.sort(key=lambda t: t["id"])
        waves.append({
            "wave": wave_idx,
            "tasks": [{
                "id": t["id"],
                "tool_name": t["tool_name"],
                "inputs": t.get("inputs", {}),
                "depends_on": t.get("depends_on", []),
            } for t in wave_tasks],
        })

        next_queue = []
        for node in queue:
            for child in children.get(node, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    next_queue.append(child)

        queue = next_queue
        wave_idx += 1

    return waves
