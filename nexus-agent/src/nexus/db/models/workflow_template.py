"""WorkflowTemplate model — reusable capability chains for common business workflows.

Replaces the old GoalTemplate table (which was dropped in Phase 1 migration).
WorkflowTemplates are matched by intent patterns at runtime and expanded into
capability chains by the SemanticPlannerNode.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base


class WorkflowTemplate(Base):
    """A reusable capability chain template.

    When a user intent matches the ``trigger_intent_pattern``, the
    ``capability_chain`` is proposed to the SemanticPlannerNode as a
    starting point for plan construction.
    """

    __tablename__ = "workflow_template"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, comment="Unique template name"
    )
    trigger_intent_pattern: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Keyword/intent pattern to match (e.g. 'reconciliation', 'dashboard')",
    )
    capability_chain: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list,
        comment=(
            "Ordered list of capability steps. "
            "Each step: {'capability': 'reconcile_transactions', 'inputs': {...}}"
        ),
    )
    description: Mapped[str] = mapped_column(
        Text, default="", comment="Human-readable description of the workflow"
    )
    priority: Mapped[int] = mapped_column(
        Integer, default=0, comment="Match priority (higher = matched first)"
    )
    max_nodes: Mapped[int] = mapped_column(
        Integer, default=10, comment="Max nodes before decomposition is triggered"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="Whether this template is active"
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, comment="Template version"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
