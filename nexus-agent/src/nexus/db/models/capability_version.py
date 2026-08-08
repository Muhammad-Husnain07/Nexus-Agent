"""Capability version history — per-capability evolution tracking."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class CapabilityVersion(Base):
    """A snapshot of a capability at a point in time (version history)."""

    __tablename__ = "capability_version"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), index=True, comment="Capability id this snapshot belongs to"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, comment="Version number")
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="Full capability contract snapshot"
    )
    changed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    change_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, comment="Whether this version is the active one")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
