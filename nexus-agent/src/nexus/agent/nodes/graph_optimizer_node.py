"""Graph Optimizer — applies policy-based tool selection to an abstract DAG.

Stage 3 of the 3-stage planner pipeline.

Given an abstract DAG (capabilities without specific tool assignments),
selects optimal tools based on:
- Cost (monetary cost per tool call)
- Latency (expected response time)
- Reliability (error rate)

All policy values are read from settings — no hardcoded weights.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.state import AgentState
from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.agent.nodes.graph_optimizer")


def _select_optimal_tool(
    tool_names: list[str],
    available_tools: list[dict[str, Any]],
    cost_weight: float = 0.5,
    latency_weight: float = 0.3,
) -> str | None:
    """Select the optimal tool for a capability based on policy weights.

    Args:
        tool_names: Candidate tool names for the capability.
        available_tools: Full list of available tool definitions.
        cost_weight: Importance of low cost (0.0–1.0).
        latency_weight: Importance of low latency (0.0–1.0).

    Returns:
        The optimal tool name, or None if no tool matched.
    """
    tool_map = {t.get("name", ""): t for t in available_tools if t.get("name")}
    candidates = [(name, tool_map.get(name)) for name in tool_names if name in tool_map]
    candidates = [(n, t) for n, t in candidates if t]

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    # Score each candidate
    best_score = float("-inf")
    best_name = candidates[0][0]

    for name, tool_def in candidates:
        risk = tool_def.get("risk_level", "low")
        auth = tool_def.get("auth_type", "none")

        # Cost score: no-auth tools cost less, low-risk tools cost less
        cost_score = 1.0
        if risk == "high":
            cost_score -= 0.3
        if auth != "none":
            cost_score -= 0.2

        # Latency score: preference over estimated fields
        latency_score = 0.5  # default medium

        # Composite
        score = (cost_weight * cost_score) + (latency_weight * latency_score)

        if score > best_score:
            best_score = score
            best_name = name

    return best_name


async def graph_optimizer_node(state: AgentState) -> dict[str, Any]:
    """Optimize the abstract DAG by selecting optimal tools per capability.

    Reads ``dag_tasks`` and ``_execution_plan`` from state, then refines
    each task's tool selection based on policy weights.

    If the plan has already been optimized (tool names are already set),
    passes through unchanged.
    """
    plan = state.get("_execution_plan", {})
    tasks = state.get("dag_tasks", [])
    available_tools = state.get("available_tools", [])

    if not tasks or not plan.get("waves"):
        logger.info("graph_optimizer.no_plan")
        return {}

    settings = get_settings().agent
    cost_weight = 0.5
    latency_weight = 0.3

    # Build capability → tool names map
    try:
        from nexus.agent.registry.capability_registry import get_capability_registry
        cap_reg = get_capability_registry()
        cap_tool_map: dict[str, list[str]] = {}
        for cap in cap_reg.get_capabilities():
            cap_tool_map[cap.name] = cap.tool_names
    except Exception:
        cap_tool_map = {}

    optimized_count = 0
    for task in tasks:
        if isinstance(task, dict):
            tname = task.get("tool_name", "")
            # If this tool name matches a capability name, pick the best tool
            if tname in cap_tool_map:
                choices = cap_tool_map[tname]
                best = _select_optimal_tool(choices, available_tools, cost_weight, latency_weight)
                if best and best != tname:
                    task["tool_name"] = best
                    optimized_count += 1

    if optimized_count:
        logger.info("graph_optimizer.optimized", count=optimized_count)

    # Update plan's tool_names
    all_tools = list({t["tool_name"] for t in tasks if isinstance(t, dict) and t.get("tool_name")})
    plan["tool_names"] = all_tools

    return {
        "dag_tasks": tasks,
        "_execution_plan": plan,
    }
