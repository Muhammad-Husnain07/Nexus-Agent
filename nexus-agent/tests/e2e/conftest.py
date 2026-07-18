"""E2E test fixtures — full FastAPI app with testcontainers.

Reuses ``tests/integration/conftest.py`` for PostgreSQL + Redis container lifecycle
and database session fixtures.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from nexus.api.depends import _current_tenant, _current_user
from nexus.api.main import create_app
from nexus.config.settings import get_settings
from nexus.security.rbac import Role, get_current_user

pytestmark = [pytest.mark.e2e]

pytest_plugins = ["tests.integration.conftest"]


@pytest_asyncio.fixture
async def full_app(
    seed_tenant: uuid.UUID,
) -> FastAPI:
    """Create a fully configured FastAPI app with dependency overrides."""
    os.environ["NEXUS_AGENT__HITL_DEFAULT"] = "false"
    os.environ["NEXUS_TOOLS__SANDBOX_ENABLED"] = "false"
    get_settings.cache_clear()

    app = create_app()

    async def mock_current_user() -> tuple[uuid.UUID, Role]:
        return uuid.UUID("00000000-0000-0000-0000-000000000002"), Role.TENANT_ADMIN

    async def mock_tenant() -> uuid.UUID:
        return seed_tenant

    async def mock_user() -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-000000000002")

    app.dependency_overrides[_current_tenant] = mock_tenant
    app.dependency_overrides[_current_user] = mock_user
    app.dependency_overrides[get_current_user] = mock_current_user

    return app


@pytest_asyncio.fixture
async def e2e_client(full_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Provide an HTTP client wired to the full app."""
    transport = ASGITransport(app=full_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
