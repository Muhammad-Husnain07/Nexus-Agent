"""Tests for the tiered rate limit middleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.datastructures import State
from starlette.requests import Request

from nexus.security.rate_limit import TieredRateLimitMiddleware


class TestTieredRateLimitMiddleware:
    """Verify rate limit tiers are applied by path."""

    @pytest.fixture
    def mock_app(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def middleware(self, mock_app: AsyncMock) -> TieredRateLimitMiddleware:
        return TieredRateLimitMiddleware(mock_app)

    def _make_request(self, path: str = "/api/v1/tools") -> MagicMock:
        req = MagicMock(spec=Request)
        req.state = State()
        req.url.path = path
        req.client.host = "127.0.0.1"
        return req

    async def test_bypasses_health_endpoints(
        self, middleware: TieredRateLimitMiddleware
    ) -> None:
        req = self._make_request("/healthz")
        call_next = AsyncMock()
        result = await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()

    async def test_calls_next_when_redis_unavailable(
        self, middleware: TieredRateLimitMiddleware
    ) -> None:
        with patch("nexus.security.rate_limit.get_redis_client", return_value=None):
            req = self._make_request()
            call_next = AsyncMock()
            await middleware.dispatch(req, call_next)
            call_next.assert_awaited_once()

    async def test_429_response_on_limit(
        self, middleware: TieredRateLimitMiddleware
    ) -> None:
        fake_redis = MagicMock()
        fake_redis.set = AsyncMock(return_value=True)

        from nexus.redis_client.rate_limiter import SlidingWindowRateLimiter

        with (
            patch("nexus.security.rate_limit.get_redis_client", return_value=fake_redis),
            patch.object(SlidingWindowRateLimiter, "acquire", return_value=False),
        ):
            req = self._make_request("/api/v1/tools")
            call_next = AsyncMock()
            resp = await middleware.dispatch(req, call_next)
            assert resp.status_code == 429
            call_next.assert_not_awaited()

    async def test_passes_through_when_under_limit(
        self, middleware: TieredRateLimitMiddleware
    ) -> None:
        fake_redis = MagicMock()
        fake_redis.set = AsyncMock(return_value=True)

        from nexus.redis_client.rate_limiter import SlidingWindowRateLimiter

        with (
            patch("nexus.security.rate_limit.get_redis_client", return_value=fake_redis),
            patch.object(SlidingWindowRateLimiter, "acquire", return_value=True),
        ):
            req = self._make_request("/api/v1/tools")
            call_next = AsyncMock()
            await middleware.dispatch(req, call_next)
            call_next.assert_awaited_once()
