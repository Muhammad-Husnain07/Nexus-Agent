"""Durable idempotency ledger model (D1/P0-D, I5).

One row per (session_id, execution_key): the atomic claim + lease for
exactly-one-winner execution, and the completed result for durable replay.
Attempt ids NEVER participate in the key — the identity is the logical
operation (scope + operation + resolved inputs).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class CompletedExecution(Base):
    """Durable execution ledger row (idempotency + lease)."""

    __tablename__ = "completed_executions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    arch_fp: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # P2-C: the run that claimed/completed this operation — every idempotency
    # row joins back to its parent invocation (request_id via the outcome).
    agent_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
