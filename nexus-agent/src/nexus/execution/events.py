"""Execution events — append-only event sourcing + emitter helpers (combined)."""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import structlog
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.base import Base as _Base
from nexus.db.base import async_session as _async_session

logger = structlog.get_logger("nexus.execution.event_store")

# The ExecutionEvent model lives on the shared ``Base`` metadata so Alembic
# autogenerate sees it (previously on a private declarative_base that Alembic
# could not detect — any schema change silently drifted).
EventBase = _Base


class ExecutionEvent(EventBase):
    """An append-only event recording a single state change during DAG execution."""

    __tablename__ = "execution_events"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    session_id: str = Column(String(255), nullable=False, index=True)
    event_type: str = Column(String(100), nullable=False, comment="Event type: task_started/task_completed/task_failed/wave_completed/execution_completed")
    task_id: str | None = Column(String(100), nullable=True, comment="Task identifier if event is task-scoped")
    tool_name: str | None = Column(String(255), nullable=True)
    payload: dict[str, Any] = Column(JSONB, default=dict, comment="Event payload (result, error, timing)")
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


async def append_event(
    session_id: str,
    event_type: str,
    task_id: str | None = None,
    tool_name: str | None = None,
    payload: dict[str, Any] | None = None,
    db_session: AsyncSession | None = None,
) -> int:
    """Append an execution event to the event store.

    Args:
        session_id: The conversation session ID.
        event_type: Type of event (task_started, task_completed, etc.).
        task_id: Optional task identifier.
        tool_name: Optional tool name.
        payload: Optional event payload dict.
        db_session: Optional DB session. Creates one if not provided.

    Returns:
        The event ID (auto-increment).
    """
    event = ExecutionEvent(
        session_id=session_id,
        event_type=event_type,
        task_id=task_id,
        tool_name=tool_name,
        payload=payload or {},
    )

    if db_session is not None:
        db_session.add(event)
        await db_session.flush()
        return event.id

    async with _async_session() as sess:
        sess.add(event)
        await sess.commit()
        return event.id


async def get_events(
    session_id: str,
    event_types: list[str] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Retrieve events for a session, optionally filtered by type.

    Args:
        session_id: The conversation session ID.
        event_types: Optional list of event types to filter by.
        limit: Maximum number of events to return (newest first).

    Returns:
        List of event dicts.
    """
    from sqlalchemy import select

    async with _async_session() as sess:
        stmt = (
            select(ExecutionEvent)
            .where(ExecutionEvent.session_id == session_id)
            .order_by(ExecutionEvent.id.desc())
            .limit(limit)
        )
        if event_types:
            stmt = stmt.where(ExecutionEvent.event_type.in_(event_types))
        result = await sess.execute(stmt)
        events = result.scalars().all()
        return [
            {
                "id": e.id,
                "event_type": e.event_type,
                "task_id": e.task_id,
                "tool_name": e.tool_name,
                "payload": e.payload,
                "created_at": str(e.created_at),
            }
            for e in events
        ]


async def replay_session(session_id: str) -> list[dict[str, Any]]:
    """Replay all events for a session in chronological order.

    Returns reconstructed execution state: tasks, results, waves.
    """
    from sqlalchemy import select

    async with _async_session() as sess:
        result = await sess.execute(
            select(ExecutionEvent)
            .where(ExecutionEvent.session_id == session_id)
            .order_by(ExecutionEvent.id.asc())
        )
        events = result.scalars().all()
        return [
            {
                "id": e.id,
                "event_type": e.event_type,
                "task_id": e.task_id,
                "tool_name": e.tool_name,
                "payload": e.payload,
                "created_at": str(e.created_at),
            }
            for e in events
        ]


# ============================================================================
# Event emitter helpers (fire-and-forget wrappers)
# ============================================================================

from typing import Any

import structlog


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
