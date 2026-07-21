"""Session and Message models for conversation history."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.db.base import Base


class Session(Base):
    """A conversation session between a user and the agent."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(512), default="New Session", comment="Session title")
    status: Mapped[str] = mapped_column(
        String(50),
        default="active",
        comment="Session status: active | archived",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=dict, comment="Arbitrary session metadata"
    )

    messages = relationship("Message", back_populates="session", passive_deletes=True)
    agent_runs = relationship("AgentRun", back_populates="session", passive_deletes=True)


class Message(Base):
    """A single message within a conversation session."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Message role: user | assistant | tool | system",
    )
    content: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=dict, comment="Rich content blocks (JSON)"
    )
    tool_calls: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="Tool call invocations (JSON)"
    )
    parent_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("message.id", ondelete="SET NULL"),
        nullable=True,
        comment="Parent message ID for branching",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="messages", passive_deletes=True)
    parent = relationship("Message", remote_side="Message.id", passive_deletes=True)
