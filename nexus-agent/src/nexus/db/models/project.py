"""Project and ProjectMembership models — cross-session organizational containers.

Projects aggregate sessions, artifacts, and memories. Sessions belong to
at most one project (nullable FK). Artifacts (dashboards, reports, configs)
are versioned and belong to a project.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.db.base import Base


class Project(Base):
    """A project — top-level organizational container.

    A project aggregates sessions, artifacts, and memories.
    Sessions can optionally belong to a project.
    """

    __tablename__ = "project"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="Project name"
    )
    description: Mapped[str] = mapped_column(
        Text, default="", comment="Project description"
    )
    status: Mapped[str] = mapped_column(
        String(50), default="active",
        comment="Project status: active | archived | completed"
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="Project owner (user ID)",
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=dict, comment="Arbitrary project metadata"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
