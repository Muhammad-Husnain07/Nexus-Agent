"""ToolCredential model — stores encrypted tool auth secrets."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base, TenantMixin, tenant_table_args


class ToolCredential(TenantMixin, Base):
    """Encrypted credential store for tool authentication secrets.

    Stores bearer tokens, basic auth credentials, OAuth tokens, and
    other auth secrets encrypted at rest using AES-256-GCM.
    """

    __tablename__ = "tool_credential"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tool.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    auth_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Authentication type: bearer, basic, oauth2, api_key",
    )
    encrypted_blob: Mapped[str] = mapped_column(
        Text, nullable=False, comment="AES-256-GCM encrypted credential payload"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Credential expiration timestamp",
    )
    last_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last credential rotation timestamp",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = tenant_table_args("tool_credential")
