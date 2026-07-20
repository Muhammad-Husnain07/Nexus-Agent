"""Passthrough tenant middleware — injects default tenant ID for all requests."""
from __future__ import annotations

import uuid
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nexus.utils.constants import DEFAULT_TENANT_ID_STR

logger = structlog.get_logger("nexus.middleware.tenant")
BYPASS_PATHS = {"/healthz", "/readyz", "/docs", "/redoc", "/openapi.json"}


class TenantMiddleware(BaseHTTPMiddleware):
    """Inject the default tenant ID for all requests."""

    async def dispatch(self, request: Request, call_next: callable) -> Response:
        if request.url.path in BYPASS_PATHS:
            return await call_next(request)
        tid = getattr(request.state, "tenant_id", None)
        if tid is None:
            tid = uuid.UUID(DEFAULT_TENANT_ID_STR)
            request.state.tenant_id = tid
        response = await call_next(request)
        response.headers["X-Tenant-ID"] = str(tid)
        return response
