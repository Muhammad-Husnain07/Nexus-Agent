"""Integration test fixtures using testcontainers for PostgreSQL+pgvector and Redis.

Starts real Docker containers, creates all tables, and provides
session-scoped DB/Redis clients for all integration tests.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from nexus.db.base import Base
from nexus.db.context import set_tenant
from nexus.tools.registry import ToolRegistry
from nexus.tools.schemas import ToolCreate

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Containers (session-scoped — start once per test run)
# ---------------------------------------------------------------------------

_POSTGRES: PostgresContainer | None = None
_REDIS: RedisContainer | None = None


def pytest_sessionfinish(session: Any) -> None:
    """Stop containers after all tests finish."""
    global _POSTGRES, _REDIS  # noqa: PLW0603
    if _REDIS is not None:
        _REDIS.stop()
        _REDIS = None
    if _POSTGRES is not None:
        _POSTGRES.stop()
        _POSTGRES = None


@pytest.fixture(scope="session")
def postgres_container() -> PostgresContainer:
    """Start a PostgreSQL 16 + pgvector container (session-scoped)."""
    global _POSTGRES  # noqa: PLW0603
    if _POSTGRES is not None:
        return _POSTGRES
    container = PostgresContainer(image="pgvector/pgvector:pg16")
    container.start()
    _POSTGRES = container
    return container


@pytest.fixture(scope="session")
def redis_container() -> RedisContainer:
    """Start a Redis 7 container (session-scoped)."""
    global _REDIS  # noqa: PLW0603
    if _REDIS is not None:
        return _REDIS
    container = RedisContainer(image="redis:7-alpine")
    container.start()
    _REDIS = container
    return container


@pytest.fixture(scope="session")
def db_url(postgres_container: PostgresContainer) -> str:
    """Get the PostgreSQL connection URL with asyncpg driver."""
    url = postgres_container.get_connection_url()
    if "+" in url and "://" in url:
        prefix, rest = url.split("://", 1)
        if "+" in prefix:
            prefix = prefix.split("+")[0]
        url = f"{prefix}+asyncpg://{rest}"
    elif "postgresql://" in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://")
    return url


@pytest.fixture(scope="session")
def redis_url(redis_container: RedisContainer) -> str:
    """Get the Redis connection URL."""
    return redis_container.get_connection_url()


# ---------------------------------------------------------------------------
# Engine & Migrations (session-scoped)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def async_engine(db_url: str) -> AsyncGenerator[AsyncEngine, None]:
    """Create a session-scoped async engine connected to the test DB.

    Creates all tables from SQLAlchemy models at setup time.
    """
    os.environ["NEXUS_SKIP_AUTO_MIGRATE"] = "1"
    import nexus.db.models  # noqa: E402, F401

    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(
    async_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Provide a function-scoped async DB session with rollback on teardown."""
    connection = await async_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)

    yield session

    await session.close()
    await transaction.rollback()
    await connection.close()


# ---------------------------------------------------------------------------
# Pre-seeded Data Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seed_tenant(db_session: AsyncSession) -> uuid.UUID:
    """Insert a test tenant and user, return tenant_id."""
    tid = uuid.UUID("11111111-1111-4111-8111-111111111111")
    uid = uuid.UUID("33333333-3333-4333-8333-333333333333")

    from nexus.db.models.tenant import Tenant
    from nexus.db.models.user import User

    tenant = Tenant(id=tid, name="Test Tenant", slug="test-tenant")
    db_session.add(tenant)
    user = User(id=uid, tenant_id=tid, email="test@example.com", role="end_user")
    db_session.add(user)
    await db_session.commit()
    return tid


@pytest_asyncio.fixture
async def seed_tools(
    db_session: AsyncSession, seed_tenant: uuid.UUID
) -> list[dict[str, Any]]:
    """Register sample tools in the test tenant and return their dicts."""
    set_tenant(seed_tenant)
    registry = ToolRegistry()
    tools_data = [
        ToolCreate(
            name="echo",
            description="Echoes back input",
            purpose="Testing",
            endpoint_url="http://localhost:9999/echo",
            http_method="POST",
            input_schema={
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
            output_schema={"type": "object", "properties": {"echo": {"type": "string"}}},
            tags=["test"],
            category="utilities",
        ),
        ToolCreate(
            name="send_email",
            description="Send an email",
            purpose="Send notifications",
            endpoint_url="http://localhost:9999/send",
            http_method="POST",
            input_schema={
                "type": "object",
                "properties": {"to": {"type": "string"}, "body": {"type": "string"}},
                "required": ["to"],
            },
            tags=["communication"],
            category="notifications",
        ),
    ]
    results = []
    for td in tools_data:
        tool = await registry.register(db_session, seed_tenant, td)
        results.append(tool.model_dump(mode="json"))
    await db_session.commit()
    return results


# ---------------------------------------------------------------------------
# HTTP Client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Provide a raw async HTTP client (not wired to the app)."""
    async with AsyncClient() as client:
        yield client
