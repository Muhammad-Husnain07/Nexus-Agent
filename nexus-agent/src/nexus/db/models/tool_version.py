"""ToolVersion model — keeps history of tool definition changes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class ToolVersion(Base):
    """Snapshot of a tool definition at a specific version number."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tool.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, comment="Snapshot version number")
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, comment="Full tool definition at this version"
    )
    changed_by: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Actor who made the change"
    )
    change_comment: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Reason or description of the change"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
