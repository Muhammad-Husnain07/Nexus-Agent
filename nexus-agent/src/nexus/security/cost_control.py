"""Per-tenant daily cost cap with model degradation.

At 100% of daily cap the tenant's model is degraded to a cheaper fallback;
at 150% all requests are rejected with QuotaExceededError.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from redis.asyncio import Redis

from nexus.errors import QuotaExceededError
from nexus.redis_client.client import get_redis_client

logger = structlog.get_logger("nexus.security.cost_control")

_DEGRADE_KEY = "cost_degraded:{tenant_id}"

DEGRADE_THRESHOLD = 1.0  # 100% of cap
HARD_REJECT_THRESHOLD = 1.5  # 150% of cap


def _seconds_until_midnight() -> int:
    now = datetime.now(UTC)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight - now).total_seconds())


class CostController:
    """Enforce per-tenant daily cost cap with tiered degradation."""

    def __init__(self, redis_client: Redis | None = None) -> None:
        self._redis = redis_client or get_redis_client()

    def _degrade_key(self, tenant_id: str) -> str:
        return _DEGRADE_KEY.format(tenant_id=tenant_id)

    async def check_and_degrade(
        self,
        tenant_id: uuid.UUID,
        cost_usd: float,
        max_cost_per_day: float,
        fallback_model: str | None = "gpt-4o-mini",
    ) -> str | None:
        """Check cost usage and return a degraded model if cap breached.

        Args:
            tenant_id: The tenant to check.
            cost_usd: Current day's accumulated cost.
            max_cost_per_day: Daily cost cap for this tenant.
            fallback_model: Model to degrade to when cap is exceeded.

        Returns:
            The fallback model name if degraded, or ``None`` for normal operation.

        Raises:
            QuotaExceededError: If usage exceeds HARD_REJECT_THRESHOLD.
        """
        if max_cost_per_day <= 0:
            return None

        ratio = cost_usd / max_cost_per_day

        if ratio >= HARD_REJECT_THRESHOLD:
            logger.warning(
                "cost.hard_reject",
                tenant_id=str(tenant_id),
                cost=cost_usd,
                cap=max_cost_per_day,
                ratio=ratio,
            )
            raise QuotaExceededError(
                f"Daily cost limit (${max_cost_per_day:.2f}) "
                f"exceeded at ${cost_usd:.2f} for tenant {tenant_id}"
            )

        if ratio >= DEGRADE_THRESHOLD and fallback_model:
            logger.info(
                "cost.degrading",
                tenant_id=str(tenant_id),
                cost=cost_usd,
                cap=max_cost_per_day,
                fallback=fallback_model,
            )
            await self._set_degraded(tenant_id, fallback_model)
            return fallback_model

        return None

    async def _set_degraded(self, tenant_id: uuid.UUID, model: str) -> None:
        if self._redis is None:
            return
        ttl = _seconds_until_midnight()
        await self._redis.set(
            self._degrade_key(str(tenant_id)),
            model,
            ex=ttl,
        )

    async def get_degraded_model(self, tenant_id: uuid.UUID) -> str | None:
        """Return the degraded model for a tenant, or None."""
        if self._redis is None:
            return None
        val = await self._redis.get(self._degrade_key(str(tenant_id)))
        return val if val else None

    async def reset_degradation(self, tenant_id: uuid.UUID) -> None:
        """Clear the degradation flag (called when quota resets)."""
        if self._redis is None:
            return
        await self._redis.delete(self._degrade_key(str(tenant_id)))
