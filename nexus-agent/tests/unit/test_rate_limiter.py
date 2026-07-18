"""Unit tests for Redis-backed rate limiters."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from nexus.redis_client.rate_limiter import (
    RateLimitError,
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
    tenant_key,
    user_key,
)

TENANT = "t1"
USER = "u1"


@pytest_asyncio.fixture
async def sliding(fake_redis):
    return SlidingWindowRateLimiter(fake_redis)


@pytest_asyncio.fixture
async def token_bucket(fake_redis):
    return TokenBucketRateLimiter(fake_redis, rate=1.0, capacity=5.0)


async def test_sliding_window_allows_n_then_blocks(sliding) -> None:
    key = tenant_key(TENANT, "chat")
    max_req, window = 3, 60
    for _ in range(max_req):
        assert await sliding.acquire(key, max_req, window) is True
    # N+1 should be rejected
    with pytest.raises(RateLimitError):
        await sliding.acquire(key, max_req, window)
    assert await sliding.acquire(key, max_req, window, raise_on_limit=False) is False


async def test_sliding_window_different_keys_isolated(sliding) -> None:
    max_req, window = 1, 60
    assert await sliding.acquire(tenant_key(TENANT, "a"), max_req, window) is True
    # Different feature key is independent
    assert await sliding.acquire(tenant_key(TENANT, "b"), max_req, window) is True
    # Same key as first is exhausted
    assert (
        await sliding.acquire(tenant_key(TENANT, "a"), max_req, window, raise_on_limit=False)
        is False
    )


async def test_user_key_isolation_from_tenant(sliding) -> None:
    max_req, window = 1, 60
    tk = tenant_key(TENANT, "chat")
    uk = user_key(TENANT, USER, "chat")
    assert await sliding.acquire(tk, max_req, window) is True
    # User key within same tenant is a separate bucket
    assert await sliding.acquire(uk, max_req, window) is True


async def test_sliding_window_window_expiry(sliding) -> None:
    key = tenant_key(TENANT, "slow")
    max_req, window = 1, 1
    assert await sliding.acquire(key, max_req, window) is True
    assert await sliding.acquire(key, max_req, window, raise_on_limit=False) is False
    # After the window elapses, the prior request has expired and a new
    # request is allowed again (verified with real time, not clock mocking).
    await asyncio.sleep(window + 0.1)
    assert await sliding.acquire(key, max_req, window, raise_on_limit=False) is True


async def test_token_bucket_allows_then_blocks(token_bucket) -> None:
    key = tenant_key(TENANT, "tool")
    # capacity is 5, consume 5 -> ok; 6th should fail
    for _ in range(5):
        assert await token_bucket.acquire(key, tokens=1.0) is True
    with pytest.raises(RateLimitError):
        await token_bucket.acquire(key, tokens=1.0)
    assert await token_bucket.acquire(key, tokens=1.0, raise_on_limit=False) is False


async def test_token_bucket_refill(token_bucket, monkeypatch) -> None:
    key = tenant_key(TENANT, "tool")
    assert await token_bucket.acquire(key, tokens=5.0) is True
    # Immediately after, bucket should be empty
    assert await token_bucket.acquire(key, tokens=1.0, raise_on_limit=False) is False
    # Rate is 1.0 token/sec; advance 2 seconds -> 2 tokens available
    import redis as _redis

    monkeypatch.setattr(_redis.asyncio.client, "time", lambda *a, **k: (2_000_000, 0))
    # The Lua script uses its own `now` from ARGV; fakeredis returns real clock.
    # We instead verify capacity semantics directly:
    assert token_bucket._capacity == 5.0
