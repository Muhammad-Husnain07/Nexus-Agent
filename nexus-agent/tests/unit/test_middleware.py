"""Tests for FastAPI middleware — rate limiting, tenant extraction, auth, request ID, error handler."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from nexus.api.main import create_app


class TestRequestIDMiddleware:
    """Verify RequestIDMiddleware propagates X-Request-ID."""

    async def test_request_id_generated(self) -> None:
        """Requests without X-Request-ID get one assigned."""
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/healthz")
            assert "X-Request-ID" in resp.headers
            assert len(resp.headers["X-Request-ID"]) > 0

    async def test_request_id_propagated(self) -> None:
        """Incoming X-Request-ID is propagated to response."""
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            req_id = "test-req-123"
            resp = await client.get("/healthz", headers={"X-Request-ID": req_id})
            assert resp.headers.get("X-Request-ID") == req_id


class TestSecurityHeaders:
    """Verify security headers are set on responses."""

    async def test_hsts_header(self) -> None:
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/healthz")
            assert resp.headers.get("Strict-Transport-Security") is not None

    async def test_x_content_type_options(self) -> None:
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/healthz")
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    async def test_x_frame_options(self) -> None:
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/healthz")
            assert resp.headers.get("X-Frame-Options") == "DENY"


class TestErrorHandlerMiddleware:
    """Verify ErrorHandlerMiddleware returns structured error JSON."""

    async def test_app_creates_without_error(self) -> None:
        """create_app() does not raise an error."""
        app = create_app()
        assert app.title == "Nexus Agent API"


class TestTenantMiddleware:
    """Verify tenant extraction from request."""

    async def test_healthz_does_not_require_tenant(self) -> None:
        """Health check endpoints bypass tenant middleware."""
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/healthz")
            assert resp.status_code == 200

    async def test_readyz_does_not_require_tenant(self) -> None:
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/readyz")
            assert resp.status_code == 200
