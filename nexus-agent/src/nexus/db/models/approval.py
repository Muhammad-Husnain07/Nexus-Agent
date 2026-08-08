"""ApprovalPolicy and ApprovalStep models — dynamic multi-stage HITL chains.

Each ApprovalPolicy defines a trigger (risk level, capability, amount threshold)
and an ordered chain of ApprovalSteps (roles, TTLs, escalation paths).

No hardcoded approver names or roles — all driven by DB metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class ApprovalPolicy(Base):
    """A multi-stage approval policy — defines who must approve what.

    The ``trigger`` JSONB field specifies when this policy applies:
    ``{"risk_level": "high", "capability": "*", "max_amount": 10000}``.

    The ``steps`` JSONB list defines the ordered approval chain, each step
    having: ``step_id``, ``role``, ``ttl_seconds``, ``escalation_role``,
    and optionally ``freed_by_jsonpath`` for conditional approvals.
    """

    __tablename__ = "approval_policy"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, comment="Unique policy name"
    )
    description: Mapped[str] = mapped_column(
        Text, default="", comment="Human-readable policy description"
    )
    trigger: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict,
        comment=(
            "Trigger conditions: {risk_level, capability, max_amount, ...}. "
            "The longest-matching trigger wins."
        ),
    )
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list,
        comment=(
            "Ordered approval chain steps. Each step: "
            "{step_id, role, ttl_seconds, escalation_role, freed_by_jsonpath}"
        ),
    )
    priority: Mapped[int] = mapped_column(
        Integer, default=0, comment="Match priority (higher = applied first)"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="Whether this policy is active"
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, comment="Policy version"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
