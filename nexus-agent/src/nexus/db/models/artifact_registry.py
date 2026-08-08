"""ArtifactRecord — durable, versioned artifact registry (Phase 8).

Artifacts become first-class runtime objects: schema-versioned, related to
producers/consumers, owned by a session/capability, with a lifecycle
(created → promoted → archived). Published artifact DATA is immutable — a
revision is a NEW row, never an in-place edit (runtime contract §8).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.db.base import Base


class ArtifactRecord(Base):
    """One immutable artifact revision."""

    __tablename__ = "artifact_registry"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True, comment="Owning session"
    )
    capability_id: Mapped[str] = mapped_column(
        String(255), default="", index=True, comment="Producing capability (stable id or name)"
    )
    tool_name: Mapped[str] = mapped_column(
        String(255), default="", index=True, comment="Producing tool"
    )
    type: Mapped[str] = mapped_column(
        String(100), default="GenericArtifact", index=True, comment="Artifact type (renderer key)"
    )
    schema_version: Mapped[str] = mapped_column(
        String(50), default="1.0", comment="Artifact schema version"
    )
    artifact_revision: Mapped[int] = mapped_column(
        Integer, default=1, comment="Revision number (immutable after publication)"
    )
    status: Mapped[str] = mapped_column(
        String(30), default="created", index=True,
        comment="Lifecycle: created | promoted | archived",
    )
    parent_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artifact_registry.id", ondelete="SET NULL"),
        nullable=True,
        comment="Relationship: derived from (producer link)",
    )
    execution_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True, comment="Producing execution task id"
    )
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="Immutable artifact payload"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    parent = relationship("ArtifactRecord", remote_side="ArtifactRecord.id", back_populates="children")
    children = relationship("ArtifactRecord", back_populates="parent")

    __table_args__ = (
        # One execution produces at most one revision of a given artifact.
        None,
    )
