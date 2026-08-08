"""Environment — deployment environments with per-environment endpoint overrides."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class Environment(Base):
    """A deployment environment (dev / staging / prod) with endpoint overrides."""

    __tablename__ = "environment"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, comment="Environment name (dev, staging, prod)"
    )
    description: Mapped[str] = mapped_column(String(512), default="")
    # Endpoint overrides: {capability_or_provider_name: {url, auth_ref, enabled}}
    endpoint_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="Per-capability endpoint overrides for this environment"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
