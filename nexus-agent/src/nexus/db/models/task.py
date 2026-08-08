"""Persistent task registry — long-running / scheduled task records.

The orchestrator stays stateless: heavy work is handed to background workers
via the task queue (Redis Streams); the ``task`` table is the durable record
for retries, progress reporting, cancellation, and scheduling.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class Task(Base):
    """A persistent task record for long-running or scheduled execution."""

    __tablename__ = "task"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    task_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True, comment="Task type (workflow_run, report, etl, ...)"
    )
    status: Mapped[str] = mapped_column(
        String(50), default="pending", index=True,
        comment="Status: pending | queued | running | paused | completed | failed | cancelled",
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, comment="Task input payload")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="Task result data")
    progress: Mapped[float] = mapped_column(
        # Allow 0..100 stored as percent
        # (Float(53) is a plain double — fine for progress 0..100)
        Integer, default=0, comment="Progress percentage (0-100)"
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, comment="Execution attempt count")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, comment="Max attempts before failure")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, comment="Cancellation flag (checked between steps)")
    schedule_cron: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="Cron expression for scheduled runs")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
