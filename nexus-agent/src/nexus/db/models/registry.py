"""Deep registry models for the Offline Registry Compiler.

These replace the runtime-inferred registries with explicit, compiled metadata.
Each model is a SQLAlchemy ORM class for PostgreSQL persistence.

No hardcoded names. All relationships are dynamic via foreign keys and JSONB contracts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy import Column as SA_Column, Table as SA_Table

from nexus.db.base import Base


class CapabilityModel(Base):
    """A registered capability — the atomic unit of work.

    Each capability declares what it consumes and produces, its ontology
    parent, and a contract describing its behavior.

    Relationships:
        providers: ProviderModel instances that can fulfill this capability.
    """

    __tablename__ = "capability"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, comment="Unique capability name"
    )
    description: Mapped[str] = mapped_column(Text, default="", comment="Human-readable description")
    ontology_parent: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Parent capability name for ontology hierarchy"
    )
    consumes: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, comment="Artifact field names required as input"
    )
    produces: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, comment="Artifact field names produced as output"
    )
    preconditions: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, comment="Conditions that must be true before execution"
    )
    postconditions: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, comment="Conditions that are true after execution"
    )
    contract: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="Contract JSON — idempotency, cost model, SLA guarantees"
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, comment="Categorization tags"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="Whether the capability is active")
    version: Mapped[int] = mapped_column(Integer, default=1, comment="Capability definition version")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    providers = relationship("ProviderModel", back_populates="capability", passive_deletes=True)


class ProviderModel(Base):
    """A provider that fulfills a capability.

    Each provider has a specific SLA, cost model, and privacy level.
    Multiple providers can fulfill the same capability.

    Relationships:
        capability: The CapabilityModel this provider fulfills.
        endpoints: EndpointModel instances for this provider.
    """

    __tablename__ = "provider"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capability.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Provider name")
    description: Mapped[str] = mapped_column(Text, default="", comment="Provider description")
    sla_p99_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="P99 latency SLA in milliseconds"
    )
    cost_per_call: Mapped[float] = mapped_column(
        Float, default=0.0, comment="Cost per invocation in USD"
    )
    privacy_level: Mapped[str] = mapped_column(
        String(50), default="low", comment="Privacy level: low | medium | high"
    )
    reliability_score: Mapped[float] = mapped_column(
        Float, default=1.0, comment="EWMA reliability score (0.0–1.0)"
    )
    rate_limit_per_minute: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Max requests per minute"
    )
    retry_policy: Mapped[str] = mapped_column(
        String(50), default="default", comment="Retry strategy: default | aggressive | conservative"
    )
    circuit_breaker_threshold: Mapped[int] = mapped_column(
        Integer, default=5, comment="Consecutive failures before circuit opens"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="Whether the provider is active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    capability = relationship("CapabilityModel", back_populates="providers")
    endpoints = relationship("EndpointModel", back_populates="provider", passive_deletes=True)


class EndpointModel(Base):
    """A concrete endpoint for a provider.

    Each provider can have multiple endpoints (e.g., different regions).

    Relationships:
        provider: The ProviderModel this endpoint belongs to.
    """

    __tablename__ = "endpoint"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False, comment="Endpoint URL")
    http_method: Mapped[str] = mapped_column(String(10), default="GET", comment="HTTP method")
    auth_type: Mapped[str] = mapped_column(String(50), default="none", comment="Authentication type")
    region: Mapped[str] = mapped_column(String(100), default="global", comment="Geographic region")
    weight: Mapped[int] = mapped_column(Integer, default=1, comment="Load balancing weight")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="Whether the endpoint is active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    provider = relationship("ProviderModel", back_populates="endpoints")


class GoalTemplateModel(Base):
    """A template that expands an intent action into atomic goals.

    Templates are YAML/JSON-based rules that map high-level actions
    (e.g., "compare", "retrieve", "create") to sequences of GoalIR.

    Relationships:
        capabilities: CapabilityModel instances required by this template.
    """

    __tablename__ = "goal_template"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, comment="Unique template name"
    )
    trigger_action: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Action that triggers this template (e.g., 'compare')"
    )
    expansion_logic: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, comment="Expansion rules — YAML/JSON defining goal sequences"
    )
    description: Mapped[str] = mapped_column(Text, default="", comment="Template description")
    version: Mapped[int] = mapped_column(Integer, default=1, comment="Template version")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="Whether the template is active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    capabilities = relationship(
        "CapabilityModel",
        secondary="goal_template_capability",
        primaryjoin="GoalTemplateModel.id == goal_template_capability.c.goal_template_id",
        secondaryjoin="goal_template_capability.c.capability_id == CapabilityModel.id",
        lazy="selectin",
    )


# Association table for goal_template → capability
goal_template_capability = SA_Table(
    "goal_template_capability",
    Base.metadata,
    SA_Column("goal_template_id", UUID(as_uuid=True), ForeignKey("goal_template.id", ondelete="CASCADE"), primary_key=True),
    SA_Column("capability_id", UUID(as_uuid=True), ForeignKey("capability.id", ondelete="CASCADE"), primary_key=True),
)
