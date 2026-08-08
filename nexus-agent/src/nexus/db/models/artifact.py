"""Artifact model — versioned project artifacts for continuous design sessions.

Artifacts track the evolution of dashboards, reports, datasets, configs,
and prompts across sessions. Each change creates a new version with
a link to the parent artifact for branching/forking.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class Artifact(Base):
    """A versioned artifact within a project.

    Each ``kind`` defines the expected content schema:
    - dashboard: {title, widgets: [{type, data, position}]}
    - report: {title, sections: [{heading, content}]}
    - dataset: {source, columns, rows}
    - config: {key, value}
    - prompt: {role, content_template}
    """

    __tablename__ = "artifact"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="Artifact kind: dashboard | report | dataset | config | prompt"
    )
    name: Mapped[str] = mapped_column(
        String(512), default="", comment="Artifact name"
    )
    parent_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artifact.id", ondelete="SET NULL"),
        nullable=True,
        comment="Parent artifact for branching/forking",
    )
    content: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="Artifact content (schema depends on kind)"
    )
    content_hash: Mapped[str] = mapped_column(
        String(64), default="", comment="SHA256 of content for dedup"
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, comment="Monotonic version number"
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("session.id", ondelete="SET NULL"),
        nullable=True, comment="Originating session ID",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
