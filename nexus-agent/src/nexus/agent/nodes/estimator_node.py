"""EstimatorNode — estimates total cost and latency for the optimized ExecutionGraph.

Reads ``_optimized_graph``, sums ``cost_estimate`` and ``latency_estimate_ms``
from each ``ToolNode`` (populated by the Compiler), and stores the estimate
in state for budget/policy checks.

Thresholds come from ``settings.compiler.max_budget_usd`` and
``settings.compiler.max_latency_ms`` — no hardcoded caps.
"""

from __future__ import annotations

import structlog

from nexus.agent.node_wrapper import context_node
from nexus.compiler.ir_models import ExecutionGraph, ToolNode
from nexus.config.settings import get_settings
from nexus.execution.context import ExecutionContext, StatePatch

logger = structlog.get_logger("nexus.agent.nodes.estimator")


@context_node
async def estimator_node(ctx: ExecutionContext) -> StatePatch:
    """Estimate total cost and latency for the optimized graph."""
    snapshot = ctx.snapshot
    graph_data = snapshot.get("_optimized_graph") or snapshot.get("_execution_graph")
    if graph_data is None:
        return StatePatch(
            version=ctx.version + 1,
            updates={
                "_cost_estimate": 0.0,
                "_latency_estimate_ms": 0,
                "_within_budget": True,
            },
        )

    graph = graph_data
    if isinstance(graph_data, dict):
        graph = ExecutionGraph(**graph_data)

    _cs = get_settings().compiler
    budget_cap = _cs.max_budget_usd
    latency_cap = _cs.max_latency_ms

    total_cost = 0.0
    max_latency = 0
    tool_count = 0

    for node in graph.nodes.values():
        if isinstance(node, ToolNode):
            total_cost += getattr(node, "cost_estimate", 0.0) or 0.0
            latency = getattr(node, "latency_estimate_ms", _cs.default_latency_ms) or _cs.default_latency_ms
            max_latency = max(max_latency, latency)
            tool_count += 1

    wave_count = len(graph.waves)
    parallel_waves = wave_count if wave_count > 1 else 1
    total_latency = max_latency * parallel_waves

    within_budget = total_cost <= budget_cap and total_latency <= latency_cap
    warnings: list[str] = []
    if total_cost > budget_cap:
        warnings.append(f"Estimated cost ${total_cost:.4f} exceeds budget ${budget_cap:.2f}")
    if total_latency > latency_cap:
        warnings.append(f"Estimated latency {total_latency}ms exceeds cap {latency_cap}ms")

    logger.info(
        "estimator_node.complete",
        total_cost=round(total_cost, 4),
        total_latency=total_latency,
        tool_count=tool_count,
        within_budget=within_budget,
    )

    return StatePatch(
        version=ctx.version + 1,
        updates={
            "_cost_estimate": total_cost,
            "_latency_estimate_ms": total_latency,
            "_within_budget": within_budget,
            "_estimate_warnings": warnings,
        },
    )
