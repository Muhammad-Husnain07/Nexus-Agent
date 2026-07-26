"""ReflectionNode — graph diffing & patching for failed task recovery.

After execution, this node:
1. Identifies failed tasks from ``_executor_failed``.
2. Uses structural graph diffing to construct a ``GraphPatch``
   containing only the failed sub-graph and its dependents.
3. Checks quorum: if failure rate exceeds threshold, routes to ``finalize``.
4. Otherwise, routes to ``retry`` with a minimal sub-graph.

The patched graph preserves the original structure — only the failed nodes
and their immediate dependents are included.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from nexus.agent.node_wrapper import context_node
from nexus.compiler.ir_models import ExecutionGraph
from nexus.execution.context import ExecutionContext, StatePatch
from nexus.execution.event_emitter import emit_graph_patched

logger = structlog.get_logger("nexus.agent.nodes.reflection")


class QuorumFailureError(Exception):
    """Raised when more than 50% of tasks fail."""


_QUORUM_THRESHOLD: float = 0.5


@context_node
async def reflection_node(ctx: ExecutionContext) -> StatePatch:
    """Evaluate execution results and produce a graph patch if needed."""
    snapshot = ctx.snapshot
    failed = snapshot.get("_executor_failed", [])
    graph_data = snapshot.get("_execution_graph")
    retry_counts = snapshot.get("_tool_retry_counts", {})
    total_retries = snapshot.get("_total_retry_count", 0)

    if not failed:
        logger.info("reflection_node.all_successful")
        return StatePatch(
            version=ctx.version + 1,
            updates={"_routing_decision": "finalize"},
        )

    graph = graph_data
    if isinstance(graph_data, dict):
        graph = ExecutionGraph(**graph_data) if graph_data else None

    if graph is None or not graph.nodes:
        return StatePatch(
            version=ctx.version + 1,
            updates={"_routing_decision": "finalize", "_recovery_available": True},
        )

    from nexus.config.settings import get_settings

    max_retries_allowed = get_settings().agent.max_reflection_retries

    if total_retries >= max_retries_allowed:
        logger.info(
            "reflection_node.global_cap_reached",
            total_retries=total_retries,
            remaining_failed=failed,
        )
        return StatePatch(
            version=ctx.version + 1,
            updates={
                "_routing_decision": "finalize",
                "_recovery_available": True,
                "_recovery_failed_tasks": list(failed),
            },
        )

    tasks_to_retry = []
    for task_id in failed:
        retries = retry_counts.get(task_id, 0)
        if retries < max_retries_allowed:
            tasks_to_retry.append(task_id)

    if not tasks_to_retry:
        return StatePatch(
            version=ctx.version + 1,
            updates={"_routing_decision": "finalize", "_recovery_available": True},
        )

    # Build graph patch: sub-graph with only failed nodes + their dependents
    patched = _build_graph_patch(graph, tasks_to_retry)

    # Check quorum: fail if too many tasks failed (threshold from settings)
    from nexus.config.settings import get_settings as _ref_settings
    quorum = _ref_settings().agent.quorum_threshold
    total_tasks = len(graph.nodes)
    if len(failed) / max(total_tasks, 1) > quorum:
        logger.error(
            "reflection_node.quorum_failed",
            failed=len(failed),
            total=total_tasks,
        )
        raise QuorumFailureError(f"More than {quorum*100:.0f}% of tasks failed.")

    new_counts = dict(retry_counts)
    for tid in tasks_to_retry:
        new_counts[tid] = new_counts.get(tid, 0) + 1

    # Emit GraphPatched event
    session_id = snapshot.get("session_id", "")
    await emit_graph_patched(
        session_id=session_id,
        patched_node_ids=list(patched.nodes.keys()) if patched else [],
        original_graph_id=graph.graph_id,
        patched_graph_id=patched.graph_id if patched else "",
    )

    logger.info(
        "reflection_node.retry",
        retry_count=len(tasks_to_retry),
        total_retries=total_retries + 1,
        patched_nodes=len(patched.nodes) if patched else 0,
    )

    return StatePatch(
        version=ctx.version + 1,
        updates={
            "_routing_decision": "retry",
            "_graph_patch": patched.model_dump() if patched else None,
            "_tool_retry_counts": new_counts,
            "_pending_tasks": tasks_to_retry,
            "_total_retry_count": total_retries + 1,
        },
    )


def _build_graph_patch(
    graph: ExecutionGraph,
    failed_ids: list[str],
) -> ExecutionGraph | None:
    """Build a sub-graph containing only failed nodes and their direct dependents.

    Structural diff: finds all downstream nodes that depend on a failed node
    and includes them in the patch. Preserves original node structure.
    """
    if not failed_ids:
        return None

    failed_set = set(failed_ids)
    nodes_to_include: set[str] = set(failed_ids)

    for nid, node in graph.nodes.items():
        if nid in failed_set:
            continue
        for dep in node.depends_on:
            if dep in failed_set:
                nodes_to_include.add(nid)
                break

    patched_nodes: dict[str, Any] = {}
    for nid in nodes_to_include:
        node = graph.nodes.get(nid)
        if node is not None:
            patched_nodes[nid] = node.model_copy(deep=True)

    if not patched_nodes:
        return None

    return ExecutionGraph(
        graph_id=str(uuid.uuid4()),
        nodes=patched_nodes,
        waves=[],
    )
