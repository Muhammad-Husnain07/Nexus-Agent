"""Direct tests for RateLimitMiddleware with mocked Redis."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.datastructures import State
from starlette.requests import Request

from nexus.middleware.rate_limit import BYPASS_PATHS, RateLimitMiddleware


class TestRateLimitMiddleware:
    """Test RateLimitMiddleware in isolation."""

    @pytest.fixture
    def middleware(self) -> RateLimitMiddleware:
        return RateLimitMiddleware(AsyncMock(), max_requests=10, window_s=60)

    def _make_request(self, path: str = "/api/v1/tools") -> MagicMock:
        req = MagicMock(spec=Request)
        req.state = State()
        req.url.path = path
        return req

    async def test_bypass_healthz(self, middleware: RateLimitMiddleware) -> None:
        req = self._make_request("/healthz")
        call_next = AsyncMock()
        await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()

    async def test_bypass_readyz(self, middleware: RateLimitMiddleware) -> None:
        req = self._make_request("/readyz")
        call_next = AsyncMock()
        await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()

    async def test_bypass_docs(self, middleware: RateLimitMiddleware) -> None:
        req = self._make_request("/docs")
        call_next = AsyncMock()
        await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()

    async def test_no_tenant_bypass(self, middleware: RateLimitMiddleware) -> None:
        with patch("nexus.middleware.rate_limit.get_tenant", return_value=None):
            req = self._make_request()
            call_next = AsyncMock()
            await middleware.dispatch(req, call_next)
            call_next.assert_awaited_once()

    async def test_no_redis_bypass(self, middleware: RateLimitMiddleware) -> None:
        with (
            patch("nexus.middleware.rate_limit.get_tenant", return_value="t1"),
            patch("nexus.middleware.rate_limit.get_redis_client", return_value=None),
        ):
            req = self._make_request()
            call_next = AsyncMock()
            await middleware.dispatch(req, call_next)
            call_next.assert_awaited_once()

    async def test_hit_limit_returns_429(self, middleware: RateLimitMiddleware) -> None:
        fake_redis = AsyncMock()
        with (
            patch("nexus.middleware.rate_limit.get_tenant", return_value="t1"),
            patch("nexus.middleware.rate_limit.get_redis_client", return_value=fake_redis),
            patch("nexus.middleware.rate_limit.SlidingWindowRateLimiter") as mock_lim,
        ):
            fake_lim = AsyncMock()
            fake_lim.acquire = AsyncMock(return_value=False)
            mock_lim.return_value = fake_lim
            req = self._make_request()
            call_next = AsyncMock()
            resp = await middleware.dispatch(req, call_next)
            assert resp.status_code == 429
            call_next.assert_not_awaited()

    async def test_under_limit_passes(self, middleware: RateLimitMiddleware) -> None:
        fake_redis = AsyncMock()
        with (
            patch("nexus.middleware.rate_limit.get_tenant", return_value="t1"),
            patch("nexus.middleware.rate_limit.get_redis_client", return_value=fake_redis),
            patch("nexus.middleware.rate_limit.SlidingWindowRateLimiter") as mock_lim,
        ):
            fake_lim = AsyncMock()
            fake_lim.acquire = AsyncMock(return_value=True)
            mock_lim.return_value = fake_lim
            req = self._make_request()
            call_next = AsyncMock()
            await middleware.dispatch(req, call_next)
            call_next.assert_awaited_once()

    def test_bypass_paths_set(self) -> None:
        assert "/healthz" in BYPASS_PATHS
        assert "/readyz" in BYPASS_PATHS
        assert "/docs" in BYPASS_PATHS
        assert "/redoc" in BYPASS_PATHS
        assert "/openapi.json" in BYPASS_PATHS

    def test_default_max_requests(self) -> None:
        mw = RateLimitMiddleware(AsyncMock())
        assert mw._max_requests == 200

    def test_custom_max_requests(self) -> None:
        mw = RateLimitMiddleware(AsyncMock(), max_requests=50, window_s=30)
        assert mw._max_requests == 50
        assert mw._window_s == 30
