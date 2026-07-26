"""Event emitter helpers — thin wrappers around ``event_store.append_event()``.

Each function extracts ``session_id`` from a context snapshot or state dict
and fires the appropriate event type with the correct payload shape.

All functions are fire-and-forget: failures are logged but not raised.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.execution.event_store import append_event

logger = structlog.get_logger("nexus.execution.event_emitter")


async def emit_planning_completed(
    session_id: str,
    workflow: dict[str, Any] | None = None,
    planner_confidence: float = 0.0,
) -> None:
    """Emit a PlanningCompleted event with the LogicalWorkflow payload."""
    try:
        await append_event(
            session_id=session_id,
            event_type="PlanningCompleted",
            payload={
                "logical_workflow": workflow or {},
                "planner_confidence": planner_confidence,
            },
        )
    except Exception as exc:
        logger.warning("event_emitter.planning_failed", error=str(exc))


async def emit_optimization_finished(
    session_id: str,
    snapshots: list[dict[str, Any]] | None = None,
    final_graph_id: str = "",
) -> None:
    """Emit an OptimizationFinished event with snapshot data."""
    try:
        await append_event(
            session_id=session_id,
            event_type="OptimizationFinished",
            payload={
                "snapshots": snapshots or [],
                "final_graph_id": final_graph_id,
            },
        )
    except Exception as exc:
        logger.warning("event_emitter.optimization_failed", error=str(exc))


async def emit_wave_completed(
    session_id: str,
    wave_index: int,
    tasks_succeeded: int,
    tasks_failed: int,
) -> None:
    """Emit a WaveCompleted event with per-wave statistics."""
    try:
        await append_event(
            session_id=session_id,
            event_type="WaveCompleted",
            payload={
                "wave_index": wave_index,
                "tasks_succeeded": tasks_succeeded,
                "tasks_failed": tasks_failed,
            },
        )
    except Exception as exc:
        logger.warning("event_emitter.wave_failed", error=str(exc))


async def emit_graph_patched(
    session_id: str,
    patched_node_ids: list[str],
    original_graph_id: str = "",
    patched_graph_id: str = "",
) -> None:
    """Emit a GraphPatched event when reflection builds a retry sub-graph."""
    try:
        await append_event(
            session_id=session_id,
            event_type="GraphPatched",
            payload={
                "patched_node_ids": patched_node_ids,
                "original_graph_id": original_graph_id,
                "patched_graph_id": patched_graph_id,
            },
        )
    except Exception as exc:
        logger.warning("event_emitter.patch_failed", error=str(exc))


async def emit_execution_finished(
    session_id: str,
    status: str = "success",
    artifacts_created: int = 0,
    total_cost: float = 0.0,
    total_latency_ms: int = 0,
) -> None:
    """Emit an ExecutionFinished event summarizing the full pipeline."""
    try:
        await append_event(
            session_id=session_id,
            event_type="ExecutionFinished",
            payload={
                "status": status,
                "artifacts_created": artifacts_created,
                "total_cost": total_cost,
                "total_latency_ms": total_latency_ms,
            },
        )
    except Exception as exc:
        logger.warning("event_emitter.finish_failed", error=str(exc))
