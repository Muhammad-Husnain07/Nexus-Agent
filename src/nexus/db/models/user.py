"""User and ApiKey models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.db.base import Base, TenantMixin, tenant_table_args


class User(TenantMixin, Base):
    """End-user within a tenant."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, comment="Email address")
    external_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="External identity provider ID"
    )
    role: Mapped[str] = mapped_column(String(50), default="member", comment="RBAC role name")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = tenant_table_args(
        "user",
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
        UniqueConstraint("tenant_id", "external_id", name="uq_user_tenant_external_id"),
    )

    tenant = relationship("Tenant", back_populates="users", passive_deletes=True)
    sessions = relationship("Session", back_populates="user", passive_deletes=True)


class ApiKey(TenantMixin, Base):
    """API key for programmatic access scoped to a tenant."""

    __tablename__ = "api_key"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="SHA-256 hash of the API key"
    )
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, comment="Permission scopes"
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Last usage timestamp"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Key expiration"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Creation timestamp"
    )

    __table_args__ = tenant_table_args(
        "api_key",
        UniqueConstraint("tenant_id", "key_hash", name="uq_apikey_tenant_hash"),
    )

    tenant = relationship("Tenant", back_populates="api_keys", passive_deletes=True)
