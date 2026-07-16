"""ASGI middleware for tenant extraction and validation."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nexus.db.base import async_session
from nexus.db.context import get_tenant as _get_tenant
from nexus.db.context import reset_tenant, set_tenant
from nexus.db.models.tenant import Tenant

logger = structlog.get_logger("nexus.middleware.tenant")

TENANT_ID_HEADER = "X-Tenant-ID"
BYPASS_PATHS = {"/healthz", "/readyz", "/docs", "/redoc", "/openapi.json"}


class TenantMiddleware(BaseHTTPMiddleware):
    """Extract tenant ID from ``X-Tenant-ID`` header, validate tenant, set context.

    Steps:
      1. Reads ``X-Tenant-ID`` from request headers.
      2. Validates it is a valid UUID v4.
      3. Looks up the ``Tenant`` in the database.
      4. Rejects suspended/archived tenants with a 403 response.
      5. Sets the tenant context via ``TenantContext`` for the duration
         of the request.
      6. Propagates the tenant ID as a response header.
    """

    async def dispatch(self, request: Request, call_next: callable) -> Response:
        reset_tenant()

        # Skip tenant resolution for public endpoints
        if request.url.path in BYPASS_PATHS:
            return await call_next(request)

        raw = request.headers.get(TENANT_ID_HEADER)
        if raw:
            try:
                tenant_id = uuid.UUID(raw.strip())
                # Validate tenant exists and is active
                async with async_session() as session:
                    stmt = select(Tenant).where(Tenant.id == tenant_id)
                    result = await session.execute(stmt)
                    tenant = result.scalar_one_or_none()

                if tenant is None:
                    logger.warning("tenant_not_found", tenant_id=str(tenant_id))
                    return Response(
                        status_code=403,
                        content='{"detail":"Tenant not found","error_code":"TENANT_NOT_FOUND"}',
                        media_type="application/json",
                    )

                if tenant.status != "active":
                    logger.warning(
                        "tenant_not_active",
                        tenant_id=str(tenant_id),
                        status=tenant.status,
                    )
                    err = tenant.status.upper()
                    _content = (
                        '{"detail":"Tenant account is '
                        + tenant.status
                        + '","error_code":"TENANT_'
                        + err
                        + '"}'
                    )
                    return Response(
                        status_code=403,
                        content=_content,
                        media_type="application/json",
                    )

                set_tenant(tenant_id)
            except ValueError:
                logger.warning("invalid_tenant_id_header", value=raw)

        response = await call_next(request)

        tid = _get_tenant_id()
        if tid is not None:
            headers = MutableHeaders(response.headers)
            headers[TENANT_ID_HEADER] = str(tid)

        return response


def _get_tenant_id() -> uuid.UUID | None:
    """Safely read the current tenant ID from context."""
    try:
        return _get_tenant()
    except Exception:
        return None
