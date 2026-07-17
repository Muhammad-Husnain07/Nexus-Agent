"""Tests for health check and readiness endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from nexus.api.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


class TestHealthEndpoint:
    async def test_healthz_returns_ok(self, client: AsyncClient) -> None:
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"

    async def test_healthz_structure(self, client: AsyncClient) -> None:
        """Health response has correct schema."""
        resp = await client.get("/healthz")
        data = resp.json()
        assert "status" in data
        assert "version" in data

    async def test_readyz_returns_200(self, client: AsyncClient) -> None:
        """Readiness endpoint returns 200."""
        resp = await client.get("/readyz")
        assert resp.status_code == 200

    async def test_readyz_checks_database(
        self, app: object, client: AsyncClient
    ) -> None:
        """Readiness includes database check."""
        resp = await client.get("/readyz")
        data = resp.json()
        assert "database" in data
        assert "redis" in data

    async def test_openapi_docs_accessible(self, client: AsyncClient) -> None:
        """OpenAPI docs endpoint is accessible."""
        resp = await client.get("/docs")
        assert resp.status_code == 200
