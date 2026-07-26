"""CompilerNode — deterministic codegen from LogicalWorkflow to ExecutionGraph.

Reads ``_logical_workflow`` from state, calls ``Compiler.compile()``,
and stores the resulting ``ExecutionGraph`` in ``_execution_graph``.
"""

from __future__ import annotations

import structlog

from nexus.agent.node_wrapper import context_node
from nexus.compiler.codegen import Compiler
from nexus.execution.context import ExecutionContext, StatePatch

logger = structlog.get_logger("nexus.agent.nodes.compiler")


@context_node
async def compiler_node(ctx: ExecutionContext) -> StatePatch:
    """Compile the LogicalWorkflow into an ExecutionGraph.

    Reads ``_logical_workflow`` from the context snapshot.
    Creates its own DB session using ``nexus.db.base.async_session``.
    """
    snapshot = ctx.snapshot
    workflow = snapshot.get("_logical_workflow")
    if workflow is None:
        logger.warning("compiler_node.no_workflow")
        return StatePatch(
            version=ctx.version + 1,
            updates={
                "_execution_graph": None,
                "errors": ["No logical workflow available for compilation"],
            },
        )

    from nexus.compiler.ir_models import LogicalWorkflow
    from nexus.compiler.resolver import CapabilityResolver
    from nexus.db.base import async_session as db_session_factory

    if isinstance(workflow, dict):
        lw = LogicalWorkflow(**workflow)
    else:
        lw = workflow

    async with db_session_factory() as db_session:
        resolver = CapabilityResolver(db_session)
        compiler = Compiler(resolver)
        graph = await compiler.compile(lw)

    logger.info(
        "compiler_node.complete",
        graph_id=graph.graph_id,
        node_count=len(graph.nodes),
        wave_count=len(graph.waves),
    )

    return StatePatch(
        version=ctx.version + 1,
        updates={"_execution_graph": graph.model_dump()},
    )
