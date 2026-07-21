"""Passthrough auth middleware — no-op, identity is not tracked."""
from __future__ import annotations

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger("nexus.middleware.auth")
BYPASS_PATHS = {"/healthz", "/readyz", "/docs", "/redoc", "/openapi.json"}

class AuthMiddleware(BaseHTTPMiddleware):
    """Passthrough — does nothing. No user identity is injected."""

    async def dispatch(self, request: Request, call_next: callable) -> Response:
        return await call_next(request)
