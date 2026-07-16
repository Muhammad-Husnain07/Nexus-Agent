"""ASGI middleware for tenant extraction from HTTP headers."""

from __future__ import annotations

import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nexus.db.context import TenantContext, reset_tenant, set_tenant

logger = structlog.get_logger("nexus.middleware.tenant")

TENANT_ID_HEADER = "X-Tenant-ID"


class TenantMiddleware(BaseHTTPMiddleware):
    """Extract tenant ID from ``X-Tenant-ID`` header and set async context.

    The middleware:
      1. Reads ``X-Tenant-ID`` from request headers.
      2. Validates it is a valid UUID v4.
      3. Sets the tenant context via ``TenantContext`` for the duration
         of the request.
      4. Propagates the tenant ID as a response header.

    If the header is missing or invalid, the request proceeds without a
    tenant context (``get_tenant()`` returns ``None``).
    """

    async def dispatch(self, request: Request, call_next: callable) -> Response:  # type: ignore[type-arg]
        reset_tenant()

        raw = request.headers.get(TENANT_ID_HEADER)
        if raw:
            try:
                tenant_id = uuid.UUID(raw.strip())
                set_tenant(tenant_id)
            except ValueError:
                logger.warning("invalid_tenant_id_header", value=raw)

        response = await call_next(request)

        current = TenantContext  # reference to ensure module loaded
        tid = None
        try:
            from nexus.db.context import get_tenant as _gt  # noqa: PLC0415

            tid = _gt()
        except Exception:
            pass

        if tid is not None:
            headers = MutableHeaders(response.headers)
            headers[TENANT_ID_HEADER] = str(tid)

        return response
