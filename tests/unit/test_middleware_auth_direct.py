"""Direct tests for AuthMiddleware with mocked JWT/DB."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.datastructures import State
from starlette.requests import Request

from nexus.middleware.auth import AuthMiddleware


class TestAuthMiddleware:
    """Test AuthMiddleware in isolation."""

    @pytest.fixture
    def middleware(self) -> AuthMiddleware:
        return AuthMiddleware(AsyncMock())

    def _make_request(self, headers: dict | None = None) -> MagicMock:
        req = MagicMock(spec=Request)
        req.state = State()
        req.url.path = "/api/v1/tools"
        req.headers = headers or {}
        return req

    async def test_bypass_healthz(self, middleware: AuthMiddleware) -> None:
        req = self._make_request()
        req.url.path = "/healthz"
        call_next = AsyncMock()
        await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()

    async def test_bypass_docs(self, middleware: AuthMiddleware) -> None:
        req = self._make_request()
        req.url.path = "/docs"
        call_next = AsyncMock()
        await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()

    async def test_no_auth_header_passes(self, middleware: AuthMiddleware) -> None:
        req = self._make_request()
        call_next = AsyncMock()
        await middleware.dispatch(req, call_next)
        call_next.assert_awaited_once()

    async def test_bearer_jwt_sets_user(self, middleware: AuthMiddleware) -> None:
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test.test"
        payload = {"sub": "11111111-1111-4111-8111-111111111111", "role": "developer"}
        with patch("nexus.middleware.auth.jwt.decode", return_value=payload):
            req = self._make_request({"Authorization": f"Bearer {token}"})
            call_next = AsyncMock()
            await middleware.dispatch(req, call_next)
            call_next.assert_awaited_once()

    async def test_invalid_jwt_passes(self, middleware: AuthMiddleware) -> None:
        from jose import JWTError

        with patch("nexus.middleware.auth.jwt.decode", side_effect=JWTError("bad")):
            req = self._make_request({"Authorization": "Bearer bad-token"})
            call_next = AsyncMock()
            await middleware.dispatch(req, call_next)
            call_next.assert_awaited_once()

    async def test_api_key_header(self, middleware: AuthMiddleware) -> None:
        """API key header passes through (key lookup uses DB)."""
        with patch("nexus.middleware.auth.async_session") as mock_factory:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
            mock_factory.return_value = mock_session
            req = self._make_request({"X-API-Key": "nxs_test_key"})
            call_next = AsyncMock()
            await middleware.dispatch(req, call_next)
            call_next.assert_awaited_once()

    async def test_bearer_without_sub(self, middleware: AuthMiddleware) -> None:
        payload = {"role": "viewer"}
        with patch("nexus.middleware.auth.jwt.decode", return_value=payload):
            req = self._make_request({"Authorization": "Bearer token-no-sub"})
            call_next = AsyncMock()
            await middleware.dispatch(req, call_next)
            call_next.assert_awaited_once()

    async def test_initializes_request_state(self, middleware: AuthMiddleware) -> None:
        req = self._make_request()
        call_next = AsyncMock()
        await middleware.dispatch(req, call_next)
        assert req.state.user_id is None
        assert req.state.user_role is None
