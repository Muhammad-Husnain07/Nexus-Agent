"""AgentRun and Approval models for tracking agent execution lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.db.base import Base


class AgentRun(Base):
    """A single execution run of the LangGraph agent graph."""

    __tablename__ = "agent_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session.id", ondelete="CASCADE"),
        nullable=False,
    )
    graph_state: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="Snapshot of the LangGraph state"
    )
    plan: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True, comment="Agent's plan steps"
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="running",
        comment="Run status: running | completed | failed | interrupted | cancelled",
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When execution finished"
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer, default=0, comment="Total LLM tokens consumed"
    )
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, comment="Total cost in USD")
    checkpoint_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="LangGraph checkpointer checkpoint ID",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="agent_runs", passive_deletes=True)
    approvals = relationship("Approval", back_populates="agent_run", passive_deletes=True)


class Approval(Base):
    """Human-in-the-loop approval record for tool calls and generic interrupts."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_run.id", ondelete="CASCADE"),
        nullable=False,
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

    agent_run = relationship("AgentRun", back_populates="approvals", passive_deletes=True)
