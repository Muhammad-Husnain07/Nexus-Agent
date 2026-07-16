"""Redis async client factory, connection pool, and FastAPI dependency."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.client import PubSub

from nexus.config.settings import get_settings


@dataclass
class _RedisState:
    """Hold the shared Redis client and its connection pool."""

    client: Redis[Any] | None = None
    pool: ConnectionPool[Any] | None = None


_state = _RedisState()


def create_redis_client() -> Redis[Any]:
    """Create a module-level async Redis client from application settings.

    Returns:
        A configured ``redis.asyncio.Redis`` instance backed by a shared
        connection pool.
    """
    if _state.client is not None:
        return _state.client

    settings = get_settings()
    _state.pool = ConnectionPool.from_url(
        settings.redis.url,
        db=settings.redis.db,
        max_connections=settings.redis.max_connections,
        decode_responses=True,
        ssl=settings.redis.ssl,
    )
    _state.client = Redis(connection_pool=_state.pool)
    return _state.client


async def init_redis() -> Redis[Any]:
    """Initialize the module-level Redis client (call from app lifespan startup)."""
    return create_redis_client()


async def close_redis() -> None:
    """Close the module-level Redis client and its connection pool."""
    if _state.client is not None:
        await _state.client.close()
        _state.client = None
    if _state.pool is not None:
        await _state.pool.disconnect()
        _state.pool = None


async def get_redis() -> AsyncGenerator[Redis[Any], None]:
    """FastAPI dependency yielding the shared Redis client."""
    client = create_redis_client()
    yield client


async def redis_health_check() -> bool:
    """Return True if the shared Redis server responds to PING."""
    client = create_redis_client()
    return await health_check(client)


async def health_check(client: Redis[Any]) -> bool:
    """Return True if the Redis server responds to PING."""
    try:
        return bool(await client.ping())
    except Exception:
        return False


@asynccontextmanager
async def pubsub_channel(client: Redis[Any], channel: str) -> AsyncIterator[PubSub]:
    """Context manager that wraps a Redis pub/sub subscription lifecycle.

    Args:
        client: The Redis client to use.
        channel: The channel name to subscribe to.

    Yields:
        The active pub/sub object for listening on ``channel``.
    """
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    try:
        yield pubsub
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
