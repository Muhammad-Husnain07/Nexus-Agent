"""Async rate limiters backed by Redis (sliding window + token bucket).

Both implementations use atomic Lua scripts to guarantee correctness under
concurrent access. Keys are namespaced per tenant or per user as required by
the multi-tenant isolation model.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from redis.asyncio import Redis

# ── Sliding window ──────────────────────────────────────────────────────────
# Adds a timestamp score to a sorted set, prunes entries older than the window,
# and reports whether the current count is within the allowed maximum.
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= max_requests then
    return 0
end
-- Unique member per request so concurrent/identical-timestamp calls each count.
local seq = redis.call('INCR', key .. ':seq')
redis.call('ZADD', key, now, now .. ':' .. seq)
redis.call('PEXPIRE', key, window)
redis.call('PEXPIRE', key .. ':seq', window)
return 1
"""

# ── Token bucket ─────────────────────────────────────────────────────────────
# Refills the bucket based on elapsed time, then atomically consumes a token if
# one is available. Returns remaining tokens (or -1 if exhausted).
_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])       -- tokens per second
local capacity = tonumber(ARGV[3])   -- max tokens
local requested = tonumber(ARGV[4])  -- tokens to consume

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
    tokens = capacity
    ts = now
end

local elapsed = math.max(0, now - ts)
local refilled = math.min(capacity, tokens + elapsed * rate)
if refilled < requested then
    return -1
end

local remaining = refilled - requested
redis.call('HMSET', key, 'tokens', remaining, 'ts', now)
redis.call('PEXPIRE', key, math.ceil(capacity / rate * 1000))
return remaining
"""  # noqa: S105 — constant name contains "TOKEN" (Lua script body)

RETRY_AFTER_HEADER = "Retry-After"


class RateLimitError(Exception):
    """Raised when a rate limit is exceeded.

    Attributes:
        key: The Redis key that hit the limit.
        retry_after_s: Suggested seconds to wait before retrying.
    """

    def __init__(self, key: str, retry_after_s: float = 0.0) -> None:
        self.key = key
        self.retry_after_s = retry_after_s
        super().__init__(f"Rate limit exceeded for key '{key}'")


def tenant_key(tenant_id: str | uuid.UUID, feature: str) -> str:
    """Build a per-tenant rate-limit key."""
    return f"rl:tenant:{tenant_id}:{feature}"


def user_key(tenant_id: str | uuid.UUID, user_id: str | uuid.UUID, feature: str) -> str:
    """Build a per-user (scoped within tenant) rate-limit key."""
    return f"rl:tenant:{tenant_id}:user:{user_id}:{feature}"


class SlidingWindowRateLimiter:
    """Sliding window counter rate limiter backed by a Redis sorted set."""

    def __init__(self, redis_client: Redis[Any]) -> None:
        self._redis = redis_client
        self._script = redis_client.register_script(_SLIDING_WINDOW_LUA)

    async def acquire(
        self,
        key: str,
        max_requests: int,
        window_s: int,
        *,
        raise_on_limit: bool = True,
    ) -> bool:
        """Attempt to consume one slot in the sliding window.

        Args:
            key: Rate-limit key (e.g. from ``tenant_key`` / ``user_key``).
            max_requests: Maximum allowed requests per window.
            window_s: Window length in seconds.
            raise_on_limit: If True, raise ``RateLimitError`` instead of
                returning False.

        Returns:
            True if the request is allowed, False otherwise (when not raising).
        """
        now_ms = int(time.time() * 1000)
        allowed = await self._script(keys=[key], args=[now_ms, window_s * 1000, max_requests])
        if allowed:
            return True
        if raise_on_limit:
            raise RateLimitError(key, retry_after_s=float(window_s))
        return False


class TokenBucketRateLimiter:
    """Token bucket rate limiter backed by a Redis hash + Lua script."""

    def __init__(self, redis_client: Redis[Any], rate: float = 1.0, capacity: float = 10.0) -> None:
        """Args:
        redis_client: Redis client.
        rate: Token refill rate (tokens per second).
        capacity: Maximum tokens the bucket can hold.
        """
        self._redis = redis_client
        self._rate = rate
        self._capacity = capacity
        self._script = redis_client.register_script(_TOKEN_BUCKET_LUA)

    async def acquire(
        self,
        key: str,
        tokens: float = 1.0,
        *,
        raise_on_limit: bool = True,
    ) -> bool:
        """Attempt to consume ``tokens`` from the bucket.

        Args:
            key: Rate-limit key.
            tokens: Number of tokens to consume.
            raise_on_limit: If True, raise ``RateLimitError`` instead of
                returning False.

        Returns:
            True if tokens were available, False otherwise (when not raising).
        """
        now_ms = int(time.time() * 1000) / 1000.0
        remaining = await self._script(
            keys=[key],
            args=[now_ms, self._rate, self._capacity, tokens],
        )
        if remaining >= 0:
            return True
        if raise_on_limit:
            refill_delay = (tokens - remaining) / self._rate
            raise RateLimitError(key, retry_after_s=refill_delay)
        return False
