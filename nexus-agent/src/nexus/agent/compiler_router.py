"""Incremental Compilation Router — routes execution outputs back to the compiler.

When a tool returns unexpected data (empty results, schema violations, failures),
this router decides whether to:
1. Re-enter the Executor (retry only the failed sub-graph via graph patch).
2. Re-enter the SemanticPlanner for a fresh LogicalWorkflow.
3. Proceed to ResponseNode (normal completion).

The router reads the ``_graph_patch`` set by ``ReflectionNode`` (which performs
actual structural graph diffing) and the ``_executor_failed`` list to determine
the minimal re-compilation path.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.compiler_router")

# Re-compilation decision constants
PROCEED = "proceed"
RETRY = "retry"
REPARSE = "reparse"
FALLBACK = "fallback"


def needs_recompilation(state: AgentState) -> str:
    """Check if execution output requires re-compilation.

    Uses structural graph diffing: examines the ``_graph_patch`` set by
    ReflectionNode. If a patch exists and is valid, routes to ``retry``
    (re-enter the Executor with only the failed sub-graph). If no patch
    or all tasks succeeded, routes to ``proceed``.

    Args:
        state: The current AgentState.

    Returns:
        One of ``"proceed"``, ``"retry"``, ``"reparse"``, or ``"fallback"``.
    """
    routing_decision = state.get("_routing_decision", "finalize")
    failed = state.get("_executor_failed", [])

    # All successful — no re-compilation needed
    if not failed:
        return PROCEED

    # Check if ReflectionNode set a retry decision (with graph patch)
    if routing_decision == "retry":
        graph_patch = state.get("_graph_patch")
        if graph_patch is not None:
            logger.info(
                "compiler_router.retry_patch",
                patched_nodes=len(graph_patch.get("nodes", {})) if isinstance(graph_patch, dict) else 0,
                failed_tasks=len(failed),
            )
            return RETRY

        # No patch but retry was requested — rebuild from scratch
        logger.info("compiler_router.reparse_no_patch", failed_tasks=len(failed))
        return REPARSE

    # Check for empty data patterns that benefit from re-extraction
    executor_results = state.get("_executor_results", {})
    for task_id in failed:
        result = executor_results.get(task_id, {})
        status = result.get("status", "")
        data = result.get("data", {})

        if status == "success" and not data:
            logger.info("compiler_router.reparse_empty", task_id=task_id)
            return REPARSE

        if status == "validation_error":
            logger.info("compiler_router.reparse_validation", task_id=task_id)
            return REPARSE

    return FALLBACK
