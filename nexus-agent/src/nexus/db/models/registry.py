"""Deep registry models for the Offline Registry Compiler.

These replace the runtime-inferred registries with explicit, compiled metadata.
Each model is a SQLAlchemy ORM class for PostgreSQL persistence.

Cost and latency are properties of the **endpoint** (the specific API route),
not the provider (the vendor). The Cost-Based Optimizer evaluates at the
endpoint level for precise constraint enforcement.

No hardcoded names. All relationships are dynamic via foreign keys and JSONB contracts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.db.base import Base


class CapabilityModel(Base):
    """A registered capability — the atomic unit of work.

    Each capability declares what it consumes and produces, its ontology
    parent, and a contract describing its behavior.

    ``logical_op_name`` is the key the Logical Planner LLM uses to reference
    this capability (e.g., ``"get_weather"``). It replaces the old intent-based
    resolution pipeline.

    Relationships:
        providers: ProviderModel instances that can fulfill this capability.
    """

    __tablename__ = "capability"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, comment="Unique capability name"
    )
    logical_op_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True,
        comment="Logical operation name used by the Semantic Planner (e.g., 'get_weather')",
    )
    batch_strategy: Mapped[str] = mapped_column(
        String(50), default="none",
        comment="Batch fusion strategy: 'none', 'fuse', or 'split'",
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
    # Input/Output knowledge — zero hardcoding in compiler or executor
    intent_profiles: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=dict,
        comment="Semantic intent → API param mappings (e.g. {'current': {'current_weather': True}})",
    )
    input_policy: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=dict,
        comment="Default params + computed field paths (e.g. {'defaults': {'timezone': 'auto'}})",
    )
    output_contract: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=dict,
        comment="Expected response shape for validation (e.g. {'required_any_of': ['$.current_weather']})",
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="Whether the capability is active")
    version: Mapped[int] = mapped_column(Integer, default=1, comment="Capability definition version")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    parent_capability_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("capability.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        comment="Parent capability for ontology hierarchy (self-referential FK)",
    )

    providers = relationship("ProviderModel", back_populates="capability", passive_deletes=True)


class ProviderModel(Base):
    """A provider that fulfills a capability.

    Each provider has a specific SLA, cost model, and privacy level.
    Multiple providers can fulfill the same capability.

    Cost and latency are moved to ``EndpointModel`` — they vary per route,
    not per vendor.

    Relationships:
        capability: The CapabilityModel this provider fulfills.
        endpoints: EndpointModel instances for this provider.
    """

    __tablename__ = "provider"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capability.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Provider name")
    description: Mapped[str] = mapped_column(Text, default="", comment="Provider description")
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

    Cost and latency live here, not on ProviderModel, because different
    API routes under the same vendor may have different pricing and
    performance characteristics.

    ``supports_batch`` enables the PassBatchFusion optimizer to merge
    multiple identical MapNode calls into a single ToolNode call.

    Relationships:
        provider: The ProviderModel this endpoint belongs to.
    """

    __tablename__ = "endpoint"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False, comment="Endpoint URL")
    http_method: Mapped[str] = mapped_column(String(10), default="GET", comment="HTTP method")
    auth_type: Mapped[str] = mapped_column(String(50), default="none", comment="Authentication type")
    region: Mapped[str] = mapped_column(String(100), default="global", comment="Geographic region")
    weight: Mapped[int] = mapped_column(Integer, default=1, comment="Load balancing weight")
    cost_per_call: Mapped[float] = mapped_column(
        Float, default=0.0, comment="Cost per invocation in USD (moved from ProviderModel)"
    )
    latency_p99_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="P99 latency in milliseconds (moved from ProviderModel.sla_p99_ms)"
    )
    supports_batch: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="Whether this endpoint supports batch requests"
    )
    required_permissions: Mapped[list[str]] = mapped_column(
        JSONB, default=list, comment="Permissions required to use this endpoint"
    )
    api_version: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None, comment="API version identifier"
    )
    deprecated: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="Whether this endpoint is deprecated"
    )
    min_tier: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None, comment="Minimum user tier required"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="Whether the endpoint is active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    provider = relationship("ProviderModel", back_populates="endpoints")


class RegistryVersionModel(Base):
    """Tracks registry compilation history — each compile records a snapshot.

    Enables incremental compilation: the compiler can diff against the last
    compiled version and only re-compile changed capabilities.
    """

    __tablename__ = "registry_version"
    __table_args__ = (
        UniqueConstraint("version", name="uq_registry_version_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, nullable=False, comment="Monotonic version number")
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, comment="SHA256 of compiled graph")
    capability_count: Mapped[int] = mapped_column(Integer, default=0, comment="Number of compiled capabilities")
    provider_count: Mapped[int] = mapped_column(Integer, default=0, comment="Number of compiled providers")
    template_count: Mapped[int] = mapped_column(Integer, default=0, comment="Number of compiled templates")
    has_cycles: Mapped[bool] = mapped_column(Boolean, default=False, comment="Whether cycles were detected")
    missing_producers: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, comment="Artifact gaps detected"
    )
    compiled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    output_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="Path to compiled JSON graph"
    )
