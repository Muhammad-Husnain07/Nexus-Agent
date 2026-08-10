"""InvocationOutcome model for per-invocation telemetry and analytics."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class InvocationOutcome(Base):
    """Persistent record of a single agent invocation for observability."""

    __tablename__ = "invocation_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="Conversation session ID"
    )
    model: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="LLM model used"
    )
    total_cost_usd: Mapped[float] = mapped_column(
        Float, default=0.0, comment="Total cost in USD"
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer, default=0, comment="Total tokens consumed"
    )
    latency_ms: Mapped[int] = mapped_column(
        Integer, default=0, comment="Total execution time in ms"
    )
    success: Mapped[bool] = mapped_column(
        default=False, comment="Whether the invocation completed without errors"
    )
    tool_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="Number of tool calls made"
    )
    tool_error_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="Number of tool calls that failed"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Error message if invocation failed"
    )
    cost_breakdown: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=dict, comment="Cost breakdown by model"
    )
    outcome_version: Mapped[int] = mapped_column(
        Integer, default=1, comment="Schema version for forward compatibility"
    )
    architecture_fingerprint: Mapped[str] = mapped_column(
        String(64), default="", nullable=False, comment="ADR 0008 architecture manifest fingerprint"
    )
    # P2-B REPRODUCIBILITY columns — the evidence to answer "exactly what
    # produced this answer?" (see nexus/observability/outcomes.py).
    request_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="API request correlation id (RequestIDMiddleware)"
    )
    agent_run_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
        comment="Per-invocation run identity (_invocation_id)"
    )
    temperature: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Finalize LLM temperature used"
    )
    seed: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="LLM seed if configured (None for parity)"
    )
    registry_fingerprint: Mapped[str] = mapped_column(
        String(64), default="", nullable=False,
        comment="Catalog/registry contract fingerprint (P1-B)"
    )
    planner_metrics: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=dict,
        comment="Plan-validator telemetry incl. per-intent coverage evidence"
    )
    intent_coverage: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=dict,
        comment="Aggregate coverage summary (evidence in planner_metrics)"
    )
    reproducibility: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=dict,
        comment="Model + temperature + prompt versions/fingerprints + arch fp"
    )
    logical_intent_graph_ref: Mapped[str] = mapped_column(
        String(64), default="", nullable=False,
        comment="SHA256 reference to the logical workflow (checkpoint)"
    )
    logical_plan_ref: Mapped[str] = mapped_column(
        String(64), default="", nullable=False,
        comment="SHA256 reference to the compiled execution graph"
    )
    attempts: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=dict, comment="Per-operation execution-key identity references"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
