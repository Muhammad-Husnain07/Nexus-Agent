"""Passthrough auth middleware — injects default user for all requests."""
from __future__ import annotations

import uuid
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nexus.utils.constants import DEFAULT_TENANT_ID_STR, DEFAULT_USER_ID_STR

logger = structlog.get_logger("nexus.middleware.auth")
BYPASS_PATHS = {"/healthz", "/readyz", "/docs", "/redoc", "/openapi.json"}

class AuthMiddleware(BaseHTTPMiddleware):
    """Inject default user/tenant identity for all requests."""

    async def dispatch(self, request: Request, call_next: callable) -> Response:
        if request.url.path in BYPASS_PATHS:
            return await call_next(request)
        request.state.user_id = uuid.UUID(DEFAULT_USER_ID_STR)
        request.state.user_role = ""
        request.state.tenant_id = uuid.UUID(DEFAULT_TENANT_ID_STR)
        return await call_next(request)
