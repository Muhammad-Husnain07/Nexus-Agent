"""Memory model for episodic, semantic, and procedural storage."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class Memory(Base):
    """A stored memory entry for the agent's long-term memory system."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session.id", ondelete="SET NULL"),
        nullable=True,
        comment="Optional originating session",
    )
    kind: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Memory kind: episodic | semantic | procedural",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="Memory content text")
    embedding: Mapped[list[float] | None] = mapped_column(
        VECTOR(4096), nullable=True, comment="Vector embedding for semantic search"
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=dict, comment="Arbitrary memory metadata"
    )
    importance: Mapped[float] = mapped_column(
        Float, default=0.0, comment="Relative importance score (0-1)"
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last time this memory was retrieved",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Consolidation fields
    status: Mapped[str | None] = mapped_column(
        String(20), default="active", comment="active | deprecated | archived"
    )
    consolidated_from: Mapped[list[str] | None] = mapped_column(
        JSONB, default=list, comment="UUIDs of source memories merged into this one"
    )
    access_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="Number of times this memory was retrieved"
    )
    base_importance: Mapped[float | None] = mapped_column(
        Float, default=None, comment="Original importance score (before decay)"
    )
    current_importance: Mapped[float | None] = mapped_column(
        Float, default=None, comment="Current importance score (after decay)"
    )
