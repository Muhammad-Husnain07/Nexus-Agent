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
    """Persistent record of a single agent invocation for observability.

    Tracks prompt versions, costs, latency, success/failure, and A/B
    experiment assignments for analytics and debugging.
    """

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
    reflection_score: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Final reflection quality score (0-10)"
    )
    tool_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="Number of tool calls made"
    )
    tool_error_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="Number of tool calls that failed"
    )
    response_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="tool | greeting | meta | memory_query"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Error message if invocation failed"
    )
    prompt_versions: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=dict, comment="Prompt name -> version mapping"
    )
    cost_breakdown: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=dict, comment="Cost breakdown by model"
    )
    ab_experiment_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="A/B experiment identifier"
    )
    ab_variant: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="A/B variant assigned"
    )
    outcome_version: Mapped[int] = mapped_column(
        Integer, default=1, comment="Schema version for forward compatibility"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
