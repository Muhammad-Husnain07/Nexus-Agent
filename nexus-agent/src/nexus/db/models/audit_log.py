"""Audit log — append-only record of important actions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class AuditLog(Base):
    """Append-only audit record: who did what, when, and the before/after."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True, comment="Actor (user id or system)"
    )
    action: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True, comment="Action type (tool_executed, approval_approved, ...)"
    )
    resource_type: Mapped[str] = mapped_column(String(100), default="", comment="Resource kind (tool, session, workflow)")
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="State before the action")
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="State after the action")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
