"""Pytest fixtures for database and Redis unit tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, create_autospec

import fakeredis.aioredis
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.context import reset_tenant, set_tenant


@pytest_asyncio.fixture
async def mock_session() -> AsyncGenerator[AsyncMock, None]:
    """Fixture providing a mock AsyncSession."""
    session = create_autospec(AsyncSession, instance=True)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.get = AsyncMock()
    session.delete = AsyncMock()
    session.add_all = MagicMock()
    yield session


@pytest_asyncio.fixture
async def fake_redis() -> AsyncGenerator[Redis, None]:
    """Fixture providing a fakeredis instance (in-memory Redis mock)."""
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.UUID("11111111-1111-4111-8111-111111111111")


@pytest.fixture
def other_tenant_id() -> uuid.UUID:
    return uuid.UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture(autouse=True)
def _clear_tenant_context() -> None:
    """Clear tenant context between tests to avoid cross-test leakage."""
    reset_tenant()


@pytest.fixture
def with_tenant(tenant_id: uuid.UUID) -> None:
    """Activate tenant context for the test scope."""
    set_tenant(tenant_id)
