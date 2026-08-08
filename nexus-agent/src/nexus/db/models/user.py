"""User model — minimal identity for role-based approval chains.

Populated from JWT claims or X-API-Key headers at middleware level.
No full auth stack — just enough for role gating.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class User(Base):
    """A user of the Nexus platform — minimal identity model."""

    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, comment="User email address"
    )
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, comment="Role identifiers (e.g. manager, compliance, finance)"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="Whether the user is active"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
