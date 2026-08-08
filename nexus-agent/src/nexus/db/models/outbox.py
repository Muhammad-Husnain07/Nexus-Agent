"""Transactional outbox — durable domain events for event-driven execution."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class OutboxEvent(Base):
    """A domain event written transactionally with business state.

    A relay (future) forwards outbox rows to Redis/Kafka/etc. without
    changing business logic — enables event-driven execution.
    """

    __tablename__ = "outbox_event"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True, comment="Domain event type"
    )
    aggregate_type: Mapped[str] = mapped_column(String(100), default="", comment="Aggregate (session, task, workflow)")
    aggregate_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(
        String(50), default="pending", index=True,
        comment="Status: pending | published | failed",
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, comment="Publish attempts")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
