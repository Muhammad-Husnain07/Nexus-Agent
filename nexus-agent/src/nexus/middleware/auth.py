"""Auth middleware — verifies identity and injects it into the request.

Modes (from settings.auth.mode):
- ``none``: passthrough — anonymous identity (embedded use)
- ``api_key``: rejects requests without a valid API key
- ``jwt``: rejects requests without a verifiable bearer token

Identity is stored on ``request.state.identity`` for downstream dependency
injection (sessions, chat, tools, approvals, memory).
"""
from __future__ import annotations

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from nexus.providers.auth.base import Identity

logger = structlog.get_logger("nexus.middleware.auth")

BYPASS_PATHS = {"/healthz", "/readyz", "/docs", "/redoc", "/openapi.json"}


class AuthMiddleware(BaseHTTPMiddleware):
    """Verifies identity per request and rejects when the mode requires it."""

    def __init__(self, app, provider=None, require_auth: bool | None = None) -> None:
        super().__init__(app)
        from nexus.config.settings import get_settings

        settings = get_settings().auth
        self._mode = settings.mode
        self._provider = provider
        self._require_auth = require_auth if require_auth is not None else (settings.mode != "none")

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in BYPASS_PATHS):
            request.state.identity = Identity(user_id="system")
            return await call_next(request)

        provider = self._provider
        if provider is None:
            from nexus.providers.auth import get_auth_provider

            try:
                provider = get_auth_provider()
            except Exception as exc:
                logger.error("auth.provider_init_failed", error=str(exc)[:200])
                return JSONResponse(
                    {"detail": "Authentication is misconfigured"},
                    status_code=503,
                )

        try:
            headers = {k.lower(): v for k, v in request.headers.items()}
            identity = await provider.authenticate(headers)
        except Exception as exc:
            logger.warning("auth.verify_failed", path=path, error=str(exc)[:200])
            identity = None

        if identity is not None:
            request.state.identity = identity
            return await call_next(request)

        if self._require_auth:
            logger.info("auth.rejected", path=path)
            return JSONResponse(
                {"detail": "Authentication required"},
                status_code=401,
            )

        # Passthrough (mode none) — anonymous identity
        request.state.identity = Identity(user_id="anonymous")
        return await call_next(request)
