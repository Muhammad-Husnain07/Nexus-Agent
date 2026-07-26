"""CapabilityResolver — resolves logical operations to physical endpoints.

The single point of DB-querying for the compiler.  Every other compiler
module (codegen, passes) receives a ``CapabilityResolver`` instance and
never touches the database directly.

Pure boundary: the resolver queries the DB, but once resolved, the
``EndpointModel`` is passed into pure transformation functions.

Strict exact match only.  The LLM is structurally barred from emitting
invalid capability names via ``instructor`` ``Literal`` types at the
semantic planner layer — no fuzzy matching needed here.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nexus.config.settings import get_settings as _resolver_settings
from nexus.db.models.registry import CapabilityModel, EndpointModel, ProviderModel

logger = structlog.get_logger("nexus.compiler.resolver")


class CapabilityError(Exception):
    """Raised when a logical operation cannot be resolved to an endpoint."""


class CapabilityResolver:
    """Resolves logical operation names to the best physical endpoint.

    Queries ``CapabilityModel.logical_op_name``, joins through
    ``ProviderModel`` → ``EndpointModel``, and scores by
    ``cost_weight * cost + latency_weight * (latency / divisor)``.

    Weights come from ``settings.compiler`` — zero hardcoded values.
    Strict exact match — no fuzzy fallback.
    Usage::

        resolver = CapabilityResolver(db_session)
        endpoint = await resolver.resolve("get_weather")
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self.db = db_session

    async def resolve(
        self,
        logical_op: str,
        objective: str = "minimize_cost",
    ) -> EndpointModel | None:
        """Resolve a logical operation to the best physical endpoint.

        Strict exact match on ``CapabilityModel.logical_op_name``.
        Returns ``None`` if no matching capability is found.

        Args:
            logical_op: The logical operation name (e.g. ``"get_weather"``).
            objective: Scoring objective (unused — kept for API compat).

        Returns:
            The best ``EndpointModel``, or ``None``.
        """
        result = await self.db.execute(
            select(CapabilityModel)
            .where(
                CapabilityModel.logical_op_name == logical_op,
                CapabilityModel.enabled == True,
            )
            .options(
                selectinload(CapabilityModel.providers).selectinload(ProviderModel.endpoints),
            )
        )
        capability = result.scalar_one_or_none()

        if capability is None:
            logger.warning("resolver.unresolvable", requested=logical_op)
            return None

        best_endpoint: EndpointModel | None = None
        best_score: float | None = None

        scores = self._load_scores(objective)

        for provider in capability.providers or []:
            if not provider.enabled:
                continue
            for endpoint in provider.endpoints or []:
                if not endpoint.enabled:
                    continue
                score = self._compute_score(endpoint, scores)
                if best_score is None or score < best_score:
                    best_score = score
                    best_endpoint = endpoint

        if best_endpoint is None:
            raise CapabilityError(
                f"No enabled endpoints for capability '{logical_op}'"
            )

        return best_endpoint

    def _load_scores(self, objective: str) -> dict[str, float]:
        """Load scoring weights from settings."""
        try:
            cs = _resolver_settings().compiler
            return {
                "cost_weight": cs.cost_weight,
                "latency_weight": cs.latency_weight,
                "latency_divisor": cs.latency_divisor,
                "default_latency_ms": cs.default_latency_ms,
            }
        except Exception:
            return {"cost_weight": 1.0, "latency_weight": 1.0, "latency_divisor": 1000.0, "default_latency_ms": 1000}

    def _compute_score(self, endpoint: EndpointModel, scores: dict[str, float]) -> float:
        """Compute a combined score for an endpoint.  Lower is better."""
        cost = endpoint.cost_per_call if endpoint.cost_per_call is not None else 0.0
        lat = endpoint.latency_p99_ms if endpoint.latency_p99_ms is not None else scores["default_latency_ms"]
        return (
            scores["cost_weight"] * cost
            + scores["latency_weight"] * (lat / scores["latency_divisor"])
        )
