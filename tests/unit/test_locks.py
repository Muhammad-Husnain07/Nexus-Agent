"""Unit tests for the distributed lock."""

from __future__ import annotations

import pytest
import pytest_asyncio

from nexus.redis_client.locks import (
    LockAcquisitionError,
    distributed_lock,
)


@pytest_asyncio.fixture
async def lock_name() -> str:
    return "agent_run:session-123"


async def test_lock_acquire_and_release(fake_redis, lock_name) -> None:
    async with distributed_lock(fake_redis, lock_name, ttl_s=30):
        assert await fake_redis.exists(f"lock:{lock_name}") == 1
    # After context exit, the lock key is removed
    assert await fake_redis.exists(f"lock:{lock_name}") == 0


async def test_lock_rejects_double_acquire(fake_redis, lock_name) -> None:
    async with distributed_lock(fake_redis, lock_name, ttl_s=30):
        # A second holder should fail to acquire the same lock
        with pytest.raises(LockAcquisitionError):
            async with distributed_lock(fake_redis, lock_name, ttl_s=30):
                pass


async def test_lock_different_names_do_not_conflict(fake_redis) -> None:
    # A different logical lock is independent
    async with (
        distributed_lock(fake_redis, "agent_run:a", ttl_s=30),
        distributed_lock(fake_redis, "agent_run:b", ttl_s=30),
    ):
        assert await fake_redis.exists("lock:agent_run:a") == 1
        assert await fake_redis.exists("lock:agent_run:b") == 1


async def test_lock_with_zero_ttl_still_releases(fake_redis, lock_name) -> None:
    async with distributed_lock(fake_redis, lock_name, ttl_s=1):
        assert await fake_redis.exists(f"lock:{lock_name}") == 1
    assert await fake_redis.exists(f"lock:{lock_name}") == 0
