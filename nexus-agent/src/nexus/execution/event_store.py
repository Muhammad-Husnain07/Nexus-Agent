"""Event Store — append-only execution event sourcing.

Every state change during DAG execution is appended as an event to the
``execution_events`` PostgreSQL table. The Executor never mutates state;
it emits events.

This enables:
- Full replay: rebuild execution state from event history.
- Time-travel debugging: inspect state at any event index.
- Projection: background workers read the event stream to update metrics.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import structlog
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from nexus.db.base import async_session as _async_session

logger = structlog.get_logger("nexus.execution.event_store")

EventBase = declarative_base()


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


async def ensure_event_store_table() -> None:
    """Create the ``execution_events`` table if it doesn't exist."""
    from nexus.db.base import get_engine
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(EventBase.metadata.create_all)


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
