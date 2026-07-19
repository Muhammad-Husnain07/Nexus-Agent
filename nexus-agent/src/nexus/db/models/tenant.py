"""Tenant model — root multi-tenant entity."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.db.base import Base
from nexus.db.models.enums import TenantStatus


class Tenant(Base):
    """A tenant/organization in the multi-tenant system."""

    __tablename__ = "tenant"
    __table_args__ = ({"comment": "Organizational tenants in the multi-tenant system"},)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Primary key",
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Human-readable tenant name"
    )
    slug: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, comment="URL-safe unique slug"
    )
    status: Mapped[TenantStatus] = mapped_column(
        String(50), default=TenantStatus.ACTIVE.value, comment="Account status"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Creation timestamp"
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="Tenant-level settings (JSON)"
    )

    users = relationship("User", back_populates="tenant", passive_deletes=True)
    api_keys = relationship("ApiKey", back_populates="tenant", passive_deletes=True)
    sessions = relationship("Session", back_populates="tenant", passive_deletes=True)
    tools = relationship("Tool", back_populates="tenant", passive_deletes=True)
    memories = relationship("Memory", back_populates="tenant", passive_deletes=True)

