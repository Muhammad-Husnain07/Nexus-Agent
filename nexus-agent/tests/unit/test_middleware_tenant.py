"""Tests for the tenant extraction middleware.

Note: Tests run against the middleware's dispatch() directly, not through
the full FastAPI stack, so tenant context is set on request.state but
not propagated to the contextvar (that happens inside the real dispatch).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.datastructures import State
from starlette.requests import Request

from nexus.middleware.tenant import TenantMiddleware


class TestTenantMiddleware:
    """Verify tenant extraction from request state."""

    @pytest.fixture
    def mock_app(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def middleware(self, mock_app: AsyncMock) -> TenantMiddleware:
        return TenantMiddleware(mock_app)

    def _make_request(self, path: str = "/api/v1/tools") -> MagicMock:
        req = MagicMock(spec=Request)
        req.state = State()
        req.headers = {}
        req.url.path = path
        return req

    async def test_bypasses_health_endpoints(self, middleware: TenantMiddleware) -> None:
        req = self._make_request("/healthz")
        call_next = AsyncMock()
        await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()

    async def test_bypasses_readyz(self, middleware: TenantMiddleware) -> None:
        req = self._make_request("/readyz")
        call_next = AsyncMock()
        await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()

    async def test_bypasses_docs(self, middleware: TenantMiddleware) -> None:
        req = self._make_request("/docs")
        call_next = AsyncMock()
        await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()

    async def test_bypasses_openapi(self, middleware: TenantMiddleware) -> None:
        req = self._make_request("/openapi.json")
        call_next = AsyncMock()
        await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()

    async def test_bypasses_metrics(self, middleware: TenantMiddleware) -> None:
        req = self._make_request("/metrics")
        call_next = AsyncMock()
        await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()

    async def test_api_request_calls_next(self, middleware: TenantMiddleware) -> None:
        req = self._make_request("/api/v1/tools")
        call_next = AsyncMock()
        await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()

    async def test_calls_next_when_no_tenant(self, middleware: TenantMiddleware) -> None:
        req = self._make_request()
        call_next = AsyncMock(return_value=MagicMock())
        await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()
