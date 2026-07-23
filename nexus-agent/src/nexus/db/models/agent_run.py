"""Approval model for human-in-the-loop interrupt tracking."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class Approval(Base):
    """Human-in-the-loop approval record for tool calls and generic interrupts."""

    __tablename__ = "approval"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Agent run identifier (optional — no FK constraint)",
    )
    interrupt_type: Mapped[str] = mapped_column(
        String(50),
        default="tool_approval",
        comment="Interrupt category: tool_approval | plan_review | final_review",
    )
    tool_call: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="The tool call that needs approval (tool_approval only)"
    )
    interrupt_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Generic payload shown to the user for any interrupt type",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="pending",
        comment="Approval status: pending | approved | rejected | edited",
    )
    decision_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Modified payload or rejection reason",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When decision was made"
    )
