"""Tests for the idempotency middleware and response cache."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.responses import JSONResponse

from nexus.errors.idempotency import (
    IdempotencyMiddleware,
    cache_idempotent_response,
    get_idempotent_response,
)


class TestIdempotencyCache:
    """Verify idempotency key-based response caching."""

    async def test_cache_and_retrieve(self) -> None:
        with patch("nexus.errors.idempotency.get_redis_client") as mock_redis:
            fake_redis = AsyncMock()
            fake_redis.set = AsyncMock(return_value=True)
            fake_redis.get = AsyncMock(return_value=json.dumps({
                "status_code": 200,
                "body": {"result": "ok"},
                "headers": {},
            }))
            mock_redis.return_value = fake_redis

            await cache_idempotent_response(
                key="test-key-123",
                status_code=200,
                body={"result": "ok"},
                headers={},
                ttl_s=3600,
            )
            cached = await get_idempotent_response("test-key-123")
            assert cached is not None
            assert cached["status_code"] == 200
            assert cached["body"] == {"result": "ok"}

    async def test_missing_key_returns_none(self) -> None:
        with patch("nexus.errors.idempotency.get_redis_client") as mock_redis:
            fake_redis = AsyncMock()
            fake_redis.get = AsyncMock(return_value=None)
            mock_redis.return_value = fake_redis
            cached = await get_idempotent_response("nonexistent-key")
            assert cached is None

    async def test_no_redis_returns_none(self) -> None:
        with patch("nexus.errors.idempotency.get_redis_client", return_value=None):
            cached = await get_idempotent_response("any-key")
            assert cached is None


class TestIdempotencyMiddleware:
    """Verify IdempotencyMiddleware intercepts duplicate requests."""

    @pytest.fixture
    def middleware(self) -> IdempotencyMiddleware:
        return IdempotencyMiddleware(AsyncMock())

    async def test_passes_through_without_key(
        self, middleware: IdempotencyMiddleware
    ) -> None:
        req = MagicMock()
        req.method = "POST"
        req.url.path = "/api/v1/sessions/abc/chat"
        req.headers = {}
        call_next = AsyncMock(return_value=JSONResponse({"ok": True}))
        with patch("nexus.errors.idempotency.get_redis_client", return_value=None):
            resp = await middleware.dispatch(req, call_next)
            assert resp is not None

    async def test_ignores_get_requests(
        self, middleware: IdempotencyMiddleware
    ) -> None:
        req = MagicMock()
        req.method = "GET"
        req.url.path = "/api/v1/tools"
        req.headers = {}
        call_next = AsyncMock(return_value=JSONResponse({"ok": True}))
        with patch("nexus.errors.idempotency.get_redis_client", return_value=None):
            await middleware.dispatch(req, call_next)
            call_next.assert_awaited_once()
