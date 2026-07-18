"""EmbedConfig model — stores embed widget configuration per token."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base, TenantMixin, tenant_table_args


class EmbedConfig(TenantMixin, Base):
    """Embedded chat widget configuration.

    Each row represents a single embed widget instance with its own token,
    theme settings, domain whitelist, and usage analytics counters.
    """

    __tablename__ = "embed_config"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(
        String(255), default="", comment="Optional human-readable label"
    )
    token: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True, comment="Scoped embed auth token"
    )
    allowed_domains: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, comment="List of allowed Origin domains for CORS"
    )
    theme: Mapped[str] = mapped_column(
        String(20), default="light", comment="Widget theme: light | dark | custom"
    )
    primary_color: Mapped[str] = mapped_column(
        String(7), default="#2563eb", comment="Primary brand color (hex)"
    )
    welcome_message: Mapped[str] = mapped_column(
        Text, default="Hello! How can I help you today?", comment="Initial agent greeting"
    )
    max_height: Mapped[int] = mapped_column(
        Integer, default=600, comment="Max widget height in pixels"
    )
    max_width: Mapped[int] = mapped_column(
        Integer, default=380, comment="Max widget width in pixels"
    )
    custom_css: Mapped[str] = mapped_column(
        Text, default="", comment="Custom CSS overrides (base64-encoded)"
    )
    rate_limit: Mapped[int] = mapped_column(
        Integer, default=30, comment="Max messages per minute"
    )
    analytics_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="Track usage analytics"
    )
    is_revoked: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="Token revoked — widget will be rejected"
    )
    message_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="Total messages sent through this embed"
    )
    active_sessions: Mapped[int] = mapped_column(
        Integer, default=0, comment="Currently active WebSocket sessions"
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Last widget interaction"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = tenant_table_args("embed_config")
