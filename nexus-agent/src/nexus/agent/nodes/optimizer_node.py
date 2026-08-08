"""OptimizerNode — runs the PassManager fixpoint optimizer on the ExecutionGraph.

Reads ``_execution_graph`` from state, creates a ``RegistryClient`` from the
DB session, runs all discovered passes (including the ``InputEnrichmentPass``)
via ``optimize_async()``, and stores the optimized graph + snapshots in state.
"""

from __future__ import annotations

import structlog

from nexus.agent.node_wrapper import context_node
from nexus.execution.context import ExecutionContext, StatePatch
from nexus.execution.events import emit_optimization_finished

logger = structlog.get_logger("nexus.agent.nodes.optimizer")


@context_node
async def optimizer_node(ctx: ExecutionContext) -> StatePatch:
    """Run the PassManager fixpoint optimizer on the ExecutionGraph.

    Creates a ``RegistryClient`` from the DB session (for the
    ``InputEnrichmentPass``) and passes it to ``optimize_async()``.
    """
    snapshot = ctx.snapshot
    graph_data = snapshot.get("_execution_graph")
    if graph_data is None:
        return StatePatch(
            version=ctx.version + 1,
            updates={
                
                "errors": ["No execution graph to optimize"],
            },
        )

    from nexus.compiler.ir_models import ExecutionGraph
    from nexus.compiler.pass_manager import optimize_async

    if isinstance(graph_data, dict):
        graph = ExecutionGraph(**graph_data)
    else:
        graph = graph_data

    # Create RegistryClient for InputEnrichmentPass
    from nexus.db.base import async_session as _opt_db
    from nexus.registry.client import RegistryClient

    pass_kwargs: dict = {}
    async with _opt_db() as db_session:
        registry = RegistryClient(db_session)
        pass_kwargs["registry"] = registry
        # Future: pass user preferences from state when available
        pass_kwargs["user_preferences"] = snapshot.get("_user_preferences", {})

        optimized, snapshots = await optimize_async(graph, pass_kwargs)

    # Emit OptimizationFinished event
    session_id = snapshot.get("session_id", "")
    await emit_optimization_finished(
        session_id=session_id,
        snapshots=[s.model_dump() for s in snapshots],
        final_graph_id=optimized.graph_id,
    )

    logger.info(
        "optimizer_node.complete",
        nodes_before=len(graph.nodes),
        nodes_after=len(optimized.nodes),
        snapshots=len(snapshots),
    )

    return StatePatch(
        version=ctx.version + 1,
        updates={
            # C13 — single canonical graph: the optimized graph REPLACES
            # ``_execution_graph`` in place (all consumers already fall back
            # to it), so the checkpoint never carries two near-identical
            # graph copies. Pass deltas live in ``_optimization_snapshots``.
            "_execution_graph": optimized.model_dump(),
            "_optimization_snapshots": [s.model_dump() for s in snapshots],
            "_graph_version": int(ctx.snapshot.get("_graph_version") or 0) + 1,
            "iteration_count": ctx.snapshot.get("iteration_count", 0) + 1,
        },
    )
