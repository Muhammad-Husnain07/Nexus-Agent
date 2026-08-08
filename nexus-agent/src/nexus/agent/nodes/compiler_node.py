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

    from nexus.capabilities.resolver import DynamicCapabilityResolver
    from nexus.compiler.ir_models import LogicalWorkflow
    from nexus.db.base import async_session as db_session_factory

    if isinstance(workflow, dict):
        lw = LogicalWorkflow(**workflow)
    else:
        lw = workflow

    # PlanCache (Phase 2): the compiled ExecutionGraph for an IDENTICAL
    # logical workflow is content-addressed + versioned (registry
    # fingerprint + compiler + artifact-schema versions) — repeated plans
    # skip codegen + resolution entirely. Cache hits are re-validated by
    # the same versioned key, so stale graphs can never be served.
    try:
        from nexus.compiler.cache import get_plan_cache

        cached_graph = await get_plan_cache().get_workflow(lw.model_dump())
    except Exception:
        cached_graph = None

    if cached_graph is not None and isinstance(cached_graph, dict):
        from nexus.compiler.ir_models import ExecutionGraph

        try:
            graph = ExecutionGraph(**cached_graph)
            logger.info(
                "compiler_node.cache_hit",
                graph_id=graph.graph_id,
                node_count=len(graph.nodes),
            )
            return StatePatch(
                version=ctx.version + 1,
                updates={
                    "_execution_graph": graph.model_dump(),
                    "_graph_version": int(snapshot.get("_graph_version") or 0) + 1,
                },
            )
        except Exception:
            pass  # malformed cache entry → recompile

    async with db_session_factory() as db_session:
        resolver = DynamicCapabilityResolver(db_session)
        compiler = Compiler(resolver)
        from nexus.capabilities.identity_context import resolver_context_from_state

        resolver_ctx = resolver_context_from_state(snapshot)
        try:
            graph = await compiler.compile(lw, resolver_context=resolver_ctx)
        except Exception as _compile_exc:
            # A compile failure (e.g. an implicit-placeholder dependency
            # cycle the validator's explicit-edge check cannot see) must
            # never kill the turn: route back to the planner (bounded by
            # ``_compile_retry_count`` AND the invocation ReasoningBudget's
            # shared replan counter — unified with the validator's loop).
            # Once the bound is exhausted, route to ResponseNode for an
            # honest answer.
            _compile_retries = int(snapshot.get("_compile_retry_count", 0) or 0)
            _budget_ok = True
            try:
                from nexus.agent.budget import budget_from_state

                _budget = budget_from_state(snapshot)
                _budget_ok = _budget.consume("replans")
            except Exception:
                _budget = None
                _budget_ok = True
            if _compile_retries < 2 and _budget_ok:
                logger.error(
                    "compiler_node.compile_failed",
                    retry=_compile_retries,
                    error=str(_compile_exc)[:300],
                )
                return StatePatch(
                    version=ctx.version + 1,
                    updates={
                        "_route_to_planner": True,
                        "_ready_to_plan": True,
                        "_compile_errors": [str(_compile_exc)[:300]],
                        "_compile_retry_count": _compile_retries + 1,
                        "_invocation_budget": _budget.to_dict()
                        if _budget is not None else {},
                    },
                )
            logger.error(
                "compiler_node.compile_abort",
                error=str(_compile_exc)[:300],
            )
            return StatePatch(
                version=ctx.version + 1,
                updates={
                    "_compile_errors": [str(_compile_exc)[:300]],
                    "errors": list(snapshot.get("errors") or [])
                    + [f"workflow failed to compile: {str(_compile_exc)[:300]}"],
                    "_routing_decision": "finalize",
                },
            )

    try:
        from nexus.compiler.cache import get_plan_cache

        await get_plan_cache().set_workflow(lw.model_dump(), graph.model_dump())
    except Exception:
        pass

    logger.info(
        "compiler_node.complete",
        graph_id=graph.graph_id,
        node_count=len(graph.nodes),
        wave_count=len(graph.waves),
    )

    return StatePatch(
        version=ctx.version + 1,
        updates={
            "_execution_graph": graph.model_dump(),
            "_graph_version": int(snapshot.get("_graph_version") or 0) + 1,
        },
    )
