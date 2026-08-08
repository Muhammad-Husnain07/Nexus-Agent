"""LongRunningWorkflow model — tracks autonomous workflows running over hours/days.

Supports pause/resume/cancel lifecycle, scheduled recurring execution,
and notification delivery on completion or failure.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class LongRunningWorkflow(Base):
    """A long-running autonomous workflow."""

    __tablename__ = "long_running_workflow"
    __table_args__ = (
        # Scheduler poll pattern: status + next_run_at
        Index("ix_long_running_workflow_status_next_run", "status", "next_run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session.id", ondelete="CASCADE"),
        nullable=False,
        comment="Originating session",
    )
    name: Mapped[str] = mapped_column(
        String(512), default="", comment="Human-readable workflow name"
    )
    status: Mapped[str] = mapped_column(
        String(50), default="running", index=True,
        comment="Status: pending | running | paused | completed | failed",
    )
    workflow_graph: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="Snapshot of the execution graph for resume",
    )
    schedule_cron: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Cron expression for recurring execution",
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Last execution timestamp",
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
        comment="Next scheduled execution",
    )
    run_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="Number of completed runs",
    )
    max_runs: Mapped[int] = mapped_column(
        Integer, default=0, comment="Max runs before auto-archiving (0 = unlimited)",
    )
    notify_on: Mapped[list[str]] = mapped_column(
        JSONB, default=list,
        comment="Events that trigger notification: ['complete', 'failure', 'status_change']",
    )
    notification_target: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Notification target (email, webhook URL, etc.)",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Failure reason if status=failed",
    )
    total_cost_usd: Mapped[float] = mapped_column(
        Float, default=0.0, comment="Accumulated cost across all runs",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
