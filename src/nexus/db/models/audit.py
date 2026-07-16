"""AuditLog model for recording all security-relevant events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.db.base import Base, TenantMixin, tenant_table_args


class AuditLog(TenantMixin, Base):
    """Immutable audit trail for security and compliance events."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="User or system actor"
    )
    action: Mapped[str] = mapped_column(String(255), nullable=False, comment="Action performed")
    resource_type: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Type of resource affected"
    )
    resource_id: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Identifier of the resource"
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="Event details (JSON)"
    )
    ip: Mapped[str] = mapped_column(String(45), default="", comment="Client IP address")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = tenant_table_args("audit_log")

    tenant = relationship("Tenant", back_populates="audit_logs", passive_deletes=True)
