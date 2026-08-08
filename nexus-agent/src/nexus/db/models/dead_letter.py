"""Dead Letter Execution model — permanently failed tool executions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class DeadLetterExecution(Base):
    """A tool execution that failed permanently and was sent to the DLQ."""

    __tablename__ = "dead_letter_execution"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Name of the tool that failed"
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="Tool definition ID"
    )
    input_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="The input arguments that were passed"
    )
    error_message: Mapped[str] = mapped_column(Text, default="", comment="The final error message")
    error_code: Mapped[str] = mapped_column(
        String(100), default="UNKNOWN", comment="Machine-readable error code"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="Number of retries attempted"
    )
    status: Mapped[str] = mapped_column(
        String(50), default="pending", comment="DLQ status: pending | replayed | archived"
    )
    original_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="When the original failure occurred",
    )
    last_retry_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Timestamp of the last retry"
    )
    replayed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When this was replayed"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
