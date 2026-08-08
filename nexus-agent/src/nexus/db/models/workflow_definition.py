"""Workflow definition — versioned deterministic workflows.

A workflow definition is the developer-defined, deterministic counterpart to
dynamic AI planning. Steps support:
- ``requires_input``: collect a value from the user (question asked in-chat)
- ``dynamic``: the step's execution plan is produced by the SemanticPlanner
  at runtime (hybrid execution)
- ``workflow_ref``: the step reuses another workflow definition as a building
  block (composition)
- ``inputs``: ``${step_1}`` style variable references into collected values
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from pgvector.sqlalchemy import VECTOR

from nexus.db.base import Base


class WorkflowDefinition(Base):
    """A versioned deterministic workflow definition."""

    __tablename__ = "workflow_definition"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, comment="Unique workflow name"
    )
    description: Mapped[str] = mapped_column(Text, default="", comment="Human-readable description")
    # trigger matching — intent pattern used by the template engine
    trigger_intent_pattern: Mapped[str] = mapped_column(
        String(255), default="", comment="Intent pattern used to match user requests"
    )
    # Steps JSON:
    # [{"id": "step_1", "description": "...", "intent": "<capability>",
    #   "requires_input": true, "question": "...", "inputs": {"k": "${step_1}"},
    #   "dynamic": false, "workflow_ref": null}]
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, comment="Ordered workflow steps (JSONB)"
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, comment="Match priority (higher first)")
    max_nodes: Mapped[int] = mapped_column(Integer, default=10, comment="Max steps before dynamic hand-off")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="Whether the workflow is active")
    version: Mapped[int] = mapped_column(Integer, default=1, comment="Workflow definition version")
    embedding: Mapped[list[float] | None] = mapped_column(
        VECTOR(4096), nullable=True, comment="Semantic embedding for hybrid workflow matching"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkflowInstance(Base):
    """An instantiated workflow execution — resume state for multi-turn runs."""

    __tablename__ = "workflow_instance"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="Workflow definition id this instance derives from",
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="Conversation session (may be null for scheduled runs)"
    )
    status: Mapped[str] = mapped_column(
        String(50), default="running",
        comment="Status: running | paused | awaiting_approval | completed | failed | cancelled",
    )
    current_step: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Current step id (resume point)"
    )
    collected: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="Collected step inputs (resume state)"
    )
    workflow_graph: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="Compiled graph snapshot for resume"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
