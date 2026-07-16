"""Distributed lock for coordinating concurrent agent runs via Redis.

Uses the standard SET NX EX pattern with a random unlock token and a Lua
release script to ensure only the lock owner can release it (avoiding
accidental release of a lock that has already expired and been re-acquired
by another caller).
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from redis.asyncio import Redis

# Releases the lock only if the caller still holds it (value matches).
_UNLOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


class LockAcquisitionError(Exception):
    """Raised when a distributed lock cannot be acquired."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Could not acquire lock '{name}'")


@asynccontextmanager
async def distributed_lock(
    redis_client: Redis[Any],
    name: str,
    ttl_s: int = 30,
) -> AsyncIterator[None]:
    """Async context manager acquiring a single-owner distributed lock.

    Args:
        redis_client: Redis client.
        name: Logical lock name (e.g. ``f"agent_run:{session_id}"``).
        ttl_s: Lock time-to-live in seconds. The lock auto-expires if the
            holder crashes, preventing deadlock.

    Raises:
        LockAcquisitionError: If the lock is already held by another caller.

    Example:
        async with distributed_lock(redis, f"agent_run:{session_id}", 60):
            ...  # only one coroutine runs this block per session_id
    """
    lock_key = f"lock:{name}"
    token = secrets.token_hex(16)
    acquired = await redis_client.set(lock_key, token, nx=True, ex=ttl_s)
    if not acquired:
        raise LockAcquisitionError(name)

    release_script = redis_client.register_script(_UNLOCK_LUA)
    try:
        yield
    finally:
        await release_script(keys=[lock_key], args=[token])
