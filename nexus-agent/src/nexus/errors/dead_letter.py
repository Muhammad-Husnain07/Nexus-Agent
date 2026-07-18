"""Dead letter queue — persists tool executions that fail after all retries.

Failed executions are stored in the ``dead_letter_execution`` table with full
context for later replay or inspection.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base, TenantMixin, tenant_table_args

logger = structlog.get_logger("nexus.errors.dead_letter")


class DeadLetterExecution(TenantMixin, Base):
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

    __table_args__ = tenant_table_args(
        "dead_letter_execution",
    )


class DeadLetterQueue:
    """Service for managing dead letter executions."""

    def __init__(self, session_factory: Any = None) -> None:
        self._session_factory = session_factory

    async def _session(self):
        if self._session_factory:
            return self._session_factory()
        from nexus.db.base import async_session

        return async_session()

    async def send(
        self,
        tenant_id: uuid.UUID,
        tool_name: str,
        input_payload: dict[str, Any],
        error_message: str,
        error_code: str = "UNKNOWN",
        retry_count: int = 0,
        tool_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Persist a failed execution to the dead letter queue.

        Args:
            tenant_id: The tenant that owns this execution.
            tool_name: Name of the tool that failed.
            input_payload: The input arguments.
            error_message: The final error message.
            error_code: Machine-readable error code.
            retry_count: Number of retries attempted before giving up.
            tool_id: Optional tool definition ID.

        Returns:
            The UUID of the dead letter execution record.
        """
        entry_id = uuid.uuid4()
        async with _get_session() as session:
            entry = DeadLetterExecution(
                id=entry_id,
                tenant_id=tenant_id,
                tool_name=tool_name,
                tool_id=tool_id,
                input_payload=input_payload,
                error_message=error_message,
                error_code=error_code,
                retry_count=retry_count,
                status="pending",
                original_timestamp=datetime.now(UTC),
            )
            session.add(entry)
            await session.commit()

        logger.info(
            "dlq.sent",
            entry_id=str(entry_id),
            tool_name=tool_name,
            error_code=error_code,
        )
        return entry_id

    async def replay(self, entry_id: uuid.UUID) -> dict[str, Any] | None:
        """Replay a dead letter execution (stub — implement actual replay logic).

        Args:
            entry_id: The DLQ entry to replay.

        Returns:
            The entry dict if found, ``None`` otherwise.
        """
        async with _get_session() as session:
            from sqlalchemy import select

            stmt = select(DeadLetterExecution).where(DeadLetterExecution.id == entry_id)
            result = await session.execute(stmt)
            entry = result.scalar_one_or_none()

            if entry is None:
                return None

            entry.status = "replayed"
            entry.replayed_at = datetime.now(UTC)
            await session.commit()

            return {
                "id": str(entry.id),
                "tool_name": entry.tool_name,
                "input_payload": entry.input_payload,
                "error_message": entry.error_message,
            }

    async def list(
        self,
        tenant_id: uuid.UUID,
        status: str | None = None,
        tool_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List dead letter executions for a tenant."""
        from sqlalchemy import select

        async with _get_session() as session:
            stmt = (
                select(DeadLetterExecution)
                .where(DeadLetterExecution.tenant_id == tenant_id)
                .order_by(DeadLetterExecution.created_at.desc())
            )
            if status:
                stmt = stmt.where(DeadLetterExecution.status == status)
            if tool_name:
                stmt = stmt.where(DeadLetterExecution.tool_name == tool_name)
            stmt = stmt.offset(offset).limit(limit)
            result = await session.execute(stmt)
            return [_to_dict(e) for e in result.scalars().all()]


def _to_dict(entry: DeadLetterExecution) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "tenant_id": str(entry.tenant_id),
        "tool_name": entry.tool_name,
        "tool_id": str(entry.tool_id) if entry.tool_id else None,
        "error_message": entry.error_message,
        "error_code": entry.error_code,
        "retry_count": entry.retry_count,
        "status": entry.status,
        "original_timestamp": entry.original_timestamp.isoformat()
        if entry.original_timestamp
        else None,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _get_session():
    """Return an async session for DLQ operations."""
    from nexus.db.base import async_session

    return async_session()
