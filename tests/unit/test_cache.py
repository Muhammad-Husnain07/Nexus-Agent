"""Unit tests for the Redis-backed cache."""

from __future__ import annotations

import pytest_asyncio

from nexus.redis_client.cache import RedisCache


@pytest_asyncio.fixture
async def cache(fake_redis):
    return RedisCache(fake_redis, prefix="test:cache")


async def test_set_get_delete(cache) -> None:
    await cache.set("k1", {"a": 1}, ttl_s=60)
    assert await cache.get("k1") == {"a": 1}
    assert await cache.exists("k1") is True
    await cache.delete("k1")
    assert await cache.get("k1") is None
    assert await cache.exists("k1") is False


async def test_expiry_not_immediate(cache, fake_redis) -> None:
    await cache.set("k2", "v", ttl_s=60)
    # Value is present immediately
    assert await cache.get("k2") == "v"


async def test_llm_response_roundtrip(cache) -> None:
    messages = [{"role": "user", "content": "hello"}]
    tools = [{"name": "search"}]
    await cache.set_llm_response("gpt-4o", messages, "hi there", tools=tools)
    assert await cache.get_llm_response("gpt-4o", messages, tools=tools) == "hi there"
    # Different messages -> different key -> cache miss
    other = [{"role": "user", "content": "bye"}]
    assert await cache.get_llm_response("gpt-4o", other, tools) is None


async def test_clear_pattern(cache) -> None:
    await cache.set("foo:1", 1)
    await cache.set("foo:2", 2)
    await cache.set("bar:1", 3)
    removed = await cache.clear_pattern("foo:*")
    assert removed == 2
    assert await cache.exists("bar:1") is True
    assert await cache.exists("foo:1") is False
