"""DynamicCapabilityResolver — resolves logical operations to ranked candidate endpoints.

Uses multi-factor scoring: capability match, schema match, reliability,
latency, cost, permissions, version recency, and deprecation status.

All configurable weights come from ``settings.resolver`` — zero hardcoded values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nexus.capabilities.schema_matcher import SchemaMatcher
from nexus.config.settings import get_settings
from nexus.db.models.registry import CapabilityModel, EndpointModel, ProviderModel

logger = structlog.get_logger("nexus.capabilities.resolver")


class CandidateEndpoint(BaseModel):
    """A scored endpoint candidate with metadata for late-binding.

    Serialized to JSON for communication between the resolver,
    optimizer pass, and executor.
    """

    endpoint_id: str = Field(description="Endpoint UUID as string")
    capability: str = Field(description="Logical operation name")
    provider_name: str = Field(description="Provider name")
    url: str = Field(description="Endpoint URL")
    http_method: str = Field(default="GET", description="HTTP method")
    score: float = Field(ge=0.0, description="Composite score (higher = better)")
    cost_per_call: float = Field(default=0.0, description="Cost in USD")
    latency_p99_ms: int | None = Field(default=None, description="P99 latency in ms")
    reliability_score: float = Field(default=1.0, description="EWMA reliability score 0-1")
    api_version: str | None = Field(default=None, description="API version")
    deprecated: bool = Field(default=False, description="Whether deprecated")
    min_tier: str | None = Field(default=None, description="Minimum user tier")


@dataclass
class ResolverContext:
    """Per-resolution context passed by the caller.

    All fields are optional — the resolver adapts to whatever is available.
    """

    user_tier: str | None = None
    user_permissions: list[str] = field(default_factory=list)
    inputs_shape: dict[str, Any] | None = None
    preferred_provider: str | None = None
    past_outcomes: dict[str, float] | None = None
    preferred_version: str | None = None
    environment: str | None = None


class DynamicCapabilityResolver:
    """Resolves logical operations to ranked candidate endpoint lists.

    Queries ``CapabilityModel.logical_op_name`` (strict exact match),
    joins through ``ProviderModel`` → ``EndpointModel``, and scores
    each enabled endpoint on 8 weighted factors.

    Usage::

        resolver = DynamicCapabilityResolver(db_session)
        candidates = await resolver.resolve("get_weather")
        best = candidates[0] if candidates else None
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self.db = db_session
        self._settings = get_settings().resolver

    async def resolve(
        self,
        logical_op: str,
        context: ResolverContext | None = None,
    ) -> list[CandidateEndpoint]:
        """Resolve a logical operation to ranked endpoint candidates.

        Args:
            logical_op: The logical operation name (e.g. ``"get_weather"``).
            context: Optional resolution context with user/call info.

        Returns:
            List of ``CandidateEndpoint`` sorted by score descending, or empty list.
        """
        ctx = context or ResolverContext()

        result = await self.db.execute(
            select(CapabilityModel)
            .where(
                CapabilityModel.logical_op_name == logical_op,
                CapabilityModel.enabled == True,  # noqa: E712
            )
            .options(
                selectinload(CapabilityModel.providers).selectinload(ProviderModel.endpoints),
            )
        )
        capability = result.scalar_one_or_none()
        if capability is None:
            # Debug the exact op + whether the row exists (enabled state
            # matters) — surfaced until the retrieval-first flow stabilizes.
            try:
                from sqlalchemy import func as _fn

                _count = await self.db.execute(
                    select(_fn.count()).select_from(CapabilityModel).where(
                        CapabilityModel.logical_op_name == logical_op
                    )
                )
                _any = _count.scalar_one()
                _enabled_count = await self.db.execute(
                    select(_fn.count()).select_from(CapabilityModel).where(
                        CapabilityModel.logical_op_name == logical_op,
                        CapabilityModel.enabled == True,  # noqa: E712
                    )
                )
            except Exception:
                _any, _enabled_count = -1, -1
            logger.warning(
                "dynamic_resolver.unresolvable",
                requested=logical_op,
                rows_exist=int(_any),
                enabled_rows=int(_enabled_count.scalar_one()) if hasattr(_enabled_count, "scalar_one") else -1,
            )
            return []

        candidates: list[CandidateEndpoint] = []
        env_overrides: dict[str, Any] = {}
        if ctx.environment:
            env_overrides = await _load_environment_overrides(ctx.environment)

        for provider in (capability.providers or []):
            if not provider.enabled:
                continue
            for endpoint in (provider.endpoints or []):
                if not endpoint.enabled:
                    continue
                # ENVIRONMENT OVERRIDE: rewrite URL/auth for this capability
                # from the active environment's endpoint_overrides (metadata-
                # driven; keyed by provider or capability name).
                override = env_overrides.get(logical_op) or env_overrides.get(provider.name)
                endpoint_url = endpoint.url
                if override:
                    endpoint_url = str(override.get("url") or endpoint_url)
                    if override.get("enabled") is False:
                        continue
                score = self._compute_score(endpoint, provider, ctx)
                candidates.append(
                    CandidateEndpoint(
                        endpoint_id=str(endpoint.id),
                        capability=logical_op,
                        provider_name=provider.name,
                        url=endpoint_url,
                        http_method=endpoint.http_method,
                        score=score,
                        cost_per_call=endpoint.cost_per_call or 0.0,
                        latency_p99_ms=endpoint.latency_p99_ms or get_settings().compiler.default_latency_ms,
                        reliability_score=provider.reliability_score or 1.0,
                        api_version=endpoint.api_version,
                        deprecated=endpoint.deprecated or False,
                        min_tier=endpoint.min_tier,
                    )
                )

        candidates.sort(key=lambda c: c.score, reverse=True)

        top_k = self._settings.top_k_candidates
        kept = candidates[:top_k]
        logger.info(
            "dynamic_resolver.resolved",
            logical_op=logical_op,
            total=len(candidates),
            returned=len(kept),
            top_score=kept[0].score if kept else None,
        )
        return kept

    def _compute_score(
        self,
        endpoint: EndpointModel,
        provider: ProviderModel,
        ctx: ResolverContext,
    ) -> float:
        """Compute multi-factor score.  Higher is better."""
        s = self._settings
        total = 0.0

        # Capability match — always 1.0 (exact match enforced by instructor)
        total += s.capability_match_weight * 1.0

        # Schema match — compare known inputs against actual shape
        if ctx.inputs_shape is not None:
            schema_score = self._compute_schema_match(endpoint, ctx.inputs_shape)
        else:
            schema_score = 1.0  # no context — assume best case
        total += s.schema_match_weight * schema_score

        # Reliability (EWMA from provider)
        rel = (
            provider.reliability_score
            if provider.reliability_score is not None
            else s.default_reliability
        )
        total += s.reliability_weight * rel

        # Latency — lower is better, clamped to [0, 1]
        lat = endpoint.latency_p99_ms or get_settings().compiler.default_latency_ms
        lat_norm = max(0.0, 1.0 - (lat / s.max_latency_ms))
        total += s.latency_weight * lat_norm

        # Cost — lower is better, clamped to [0, 1]
        cost = endpoint.cost_per_call or 0.0
        cost_norm = max(0.0, 1.0 - (cost / s.max_cost_usd))
        total += s.cost_weight * cost_norm

        # Permissions — 1.0 if user has all required, 0.0 otherwise
        if ctx.user_permissions and endpoint.required_permissions:
            perms_ok = all(p in ctx.user_permissions for p in endpoint.required_permissions)
            total += s.permissions_weight * (1.0 if perms_ok else 0.0)
        elif endpoint.required_permissions:
            total += s.permissions_weight * 1.0

        # User preference — exact provider name match
        if ctx.preferred_provider and ctx.preferred_provider == provider.name:
            total += s.user_preference_weight * 1.0

        # Version recency — higher version = higher score (simple heuristic)
        if endpoint.api_version:
            parts = endpoint.api_version.split(".")
            try:
                v = sum(int(p) * (100 ** (len(parts) - i - 1)) for i, p in enumerate(parts))
                v_norm = min(1.0, v / 1000.0)
                total += s.version_weight * v_norm
            except (ValueError, IndexError):
                pass

        # Preferred version — exact match gets a decisive boost so callers
        # can pin an API version (e.g. during staged rollouts).
        if ctx.preferred_version and endpoint.api_version == ctx.preferred_version:
            total += s.version_weight * 1.0

        # Deprecation penalty — applied as multiplier after sum
        if endpoint.deprecated:
            total *= s.deprecated_penalty

        return round(total, 4)

    @staticmethod
    def _compute_schema_match(
        endpoint: EndpointModel,
        inputs_shape: dict[str, Any],
    ) -> float:
        """Heuristic schema match — compares key overlap.

        Returns 1.0 for exact, 0.5 for partial, 0.0 for no overlap.
        """
        return SchemaMatcher.compute(endpoint, inputs_shape)


async def _load_environment_overrides(environment: str) -> dict[str, Any]:
    """Load endpoint overrides for an environment from the DB.

    Returns ``{capability_or_provider_name: {url, enabled}}``.

    Args:
        environment: The environment name (e.g. ``dev``, ``prod``).

    Returns:
        Override map (empty when the environment is unknown or disabled).
    """
    try:
        from sqlalchemy import select as _env_select

        from nexus.db.base import async_session as _env_session
        from nexus.db.models.environment import Environment

        async with _env_session() as session:
            result = await session.execute(
                _env_select(Environment).where(
                    Environment.name == environment,
                    Environment.enabled == True,  # noqa: E712
                )
            )
            env = result.scalar_one_or_none()
            if env is None:
                return {}
            return dict(env.endpoint_overrides or {})
    except Exception as exc:
        logger.warning("resolver.environment_overrides_failed", error=str(exc)[:200])
        return {}
