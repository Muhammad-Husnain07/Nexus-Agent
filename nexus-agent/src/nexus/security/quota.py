"""Per-tenant quota enforcement backed by Redis counters."""

from __future__ import annotations

import uuid
from datetime import date

from redis.asyncio import Redis

from nexus.errors import QuotaExceededError
from nexus.redis_client.client import get_redis_client


def _today_key(tenant_id: str, counter: str) -> str:
    return f"quota:{tenant_id}:{counter}:{date.today().isoformat()}"


async def _check_and_increment(
    redis: Redis,
    key: str,
    max_value: int,
    ttl_s: int = 86400,
) -> bool:
    """Atomically increment a Redis counter and check against *max_value*."""
    val = await redis.incr(key)
    if val == 1:
        await redis.expire(key, ttl_s)
    return not val > max_value


class QuotaEnforcer:
    """Enforce per-tenant usage quotas using Redis counters.

    Quota limits are read from the ``Tenant.settings`` JSONB blob under
    the ``quotas`` key.  The settings dict is expected to contain:

    .. code-block:: python

        {
            "max_tools": 50,
            "max_sessions_per_day": 1000,
            "max_tokens_per_day": 5_000_000,
            "max_cost_usd_per_day": 50.0,
        }

    Raises ``QuotaExceededError`` when a limit is hit.
    """

    def __init__(self, redis_client: Redis | None = None) -> None:
        self._redis = redis_client or get_redis_client()

    async def check_tool_count(  # noqa: E501
        self, tenant_id: uuid.UUID, current_count: int, max_tools: int
    ) -> None:
        """Check that the tenant has not exceeded its tool registration limit."""
        if current_count >= max_tools:
            raise QuotaExceededError(
                f"Tool registration limit ({max_tools}) reached for tenant {tenant_id}"
            )

    async def check_session_creation(self, tenant_id: uuid.UUID, max_per_day: int) -> None:
        """Check daily session creation quota."""
        if self._redis is None:
            return
        key = _today_key(str(tenant_id), "sessions")
        ok = await _check_and_increment(self._redis, key, max_per_day)
        if not ok:
            raise QuotaExceededError(
                f"Daily session creation limit ({max_per_day}) exceeded for tenant {tenant_id}"
            )

    async def check_token_usage(self, tenant_id: uuid.UUID, tokens: int, max_per_day: int) -> None:
        """Check daily token usage quota."""
        if self._redis is None:
            return
        key = _today_key(str(tenant_id), "tokens")
        val = await self._redis.incrby(key, tokens)
        if val == tokens:
            await self._redis.expire(key, 86400)
        if val > max_per_day:
            raise QuotaExceededError(
                f"Daily token usage limit ({max_per_day}) exceeded for tenant {tenant_id}"
            )

    async def check_cost(self, tenant_id: uuid.UUID, cost_usd: float, max_per_day: float) -> None:
        """Check daily cost quota."""
        if self._redis is None:
            return
        key = _today_key(str(tenant_id), "cost")
        cents = int(cost_usd * 100)
        val = await self._redis.incrby(key, cents)
        if val == cents:
            await self._redis.expire(key, 86400)
        if val / 100.0 > max_per_day:
            raise QuotaExceededError(
                f"Daily cost limit (${max_per_day:.2f}) exceeded for tenant {tenant_id}"
            )
