"""Tool (capability registration) and ToolExecution models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.db.base import Base


class Tool(Base):
    """A registered tool/capability that the agent can invoke."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, comment="Unique tool name"
    )
    description: Mapped[str] = mapped_column(Text, default="", comment="Human-readable description")
    purpose: Mapped[str] = mapped_column(
        Text, default="", comment="What the tool does and when to use it"
    )
    endpoint_url: Mapped[str] = mapped_column(String(2048), default="", comment="API endpoint URL")
    http_method: Mapped[str] = mapped_column(
        String(10), default="GET", comment="HTTP method: GET | POST | PUT | DELETE | PATCH"
    )
    auth_type: Mapped[str] = mapped_column(
        String(50), default="none", comment="Authentication type"
    )
    auth_ref: Mapped[str] = mapped_column(
        String(255), default="", comment="Reference to stored auth config"
    )
    input_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="JSON Schema for input parameters"
    )
    output_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="JSON Schema for output"
    )
    validation_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="Business validation rules"
    )
    examples: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, comment="Example invocations"
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, comment="Categorization tags"
    )
    category: Mapped[str] = mapped_column(
        String(255), default="general", comment="Functional category"
    )
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="Requires HITL approval"
    )
    risk_level: Mapped[str] = mapped_column(
        String(50),
        default="low",
        comment="Risk level: low | medium | high",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="Whether the tool is active"
    )
    rate_limit_per_minute: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None, comment="Max requests per minute (null = unlimited)"
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        VECTOR(768), nullable=True, comment="Semantic embedding for discovery"
    )
    version: Mapped[int] = mapped_column(Integer, default=1, comment="Tool definition version")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    executions = relationship("ToolExecution", back_populates="tool", passive_deletes=True)


class ToolExecution(Base):
    """Record of a single tool invocation and its result."""

    __tablename__ = "tool_execution"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tool.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_run.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="Input arguments sent to the tool"
    )
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="Raw response from the tool"
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="success",
        comment="Execution outcome: success | error | timeout | interrupted",
    )
    http_status: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="HTTP response status code"
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer, default=0, comment="Execution duration in milliseconds"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Error message if failed"
    )
    retried: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="Whether this was a retry"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tool = relationship("Tool", back_populates="executions", passive_deletes=True)
