"""ASGI middleware for tenant extraction and validation.

Security invariants maintained by this middleware:

1. Authenticated users always operate in the tenant they were issued
   credentials for (embedded in the JWT as a ``tid`` claim or in the
   ``ApiKey.tenant_id`` column).  The client-supplied ``X-Tenant-ID``
   header is **ignored** for authenticated requests unless it matches
   the authenticated tenant — any mismatch produces a 403
   ``TENANT_MISMATCH`` error.

2. Unauthenticated requests (rare, but possible for certain admin
   bootstrap flows) fall back to header-based tenant resolution.

3. The auth-verified tenant is also recorded in a contextvar for
   defense-in-depth cross-checking at the repository layer.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nexus.db.base import async_session
from nexus.db.context import (
    get_tenant as _get_tenant,
    reset_asserted_tenant,
    reset_tenant,
    set_asserted_tenant,
    set_tenant,
)
from nexus.db.models.tenant import Tenant

logger = structlog.get_logger("nexus.middleware.tenant")

TENANT_ID_HEADER = "X-Tenant-ID"
BYPASS_PATHS = {"/healthz", "/readyz", "/docs", "/redoc", "/openapi.json"}

_TENANT_MISMATCH_RESPONSE = Response(
    status_code=403,
    content=(
        '{"detail":"Tenant mismatch: authenticated tenant does not match '
        'request tenant","error_code":"TENANT_MISMATCH"}'
    ),
    media_type="application/json",
)


class TenantMiddleware(BaseHTTPMiddleware):
    """Extract tenant ID from authenticated identity or ``X-Tenant-ID`` header.

    Steps:
      1. If the caller is already authenticated (``request.state.user_id``
         and ``request.state.tenant_id`` are set), use the authenticated
         tenant — ignore the header unless it matches.
      2. If the header is present and the caller is authenticated but the
         header value differs → 403 ``TENANT_MISMATCH``.
      3. If the caller is unauthenticated, fall back to header-based
         resolution (existing behaviour).
      4. Validates the resolved tenant exists and is active.
      5. Sets the tenant context via ``TenantContext`` for the duration
         of the request.
      6. Records the auth-verified tenant in ``_asserted_tenant_id_var``
         for defense-in-depth at the repository layer.
      7. Propagates the tenant ID as a response header.
    """

    async def dispatch(self, request: Request, call_next: callable) -> Response:
        reset_tenant()
        reset_asserted_tenant()

        # Skip tenant resolution for public endpoints
        if request.url.path in BYPASS_PATHS:
            return await call_next(request)

        user_id = getattr(request.state, "user_id", None)
        auth_tenant_id: uuid.UUID | None = getattr(request.state, "tenant_id", None)

        header_raw = request.headers.get(TENANT_ID_HEADER)

        # ── Authenticated path ────────────────────────────────────────────
        if user_id is not None and auth_tenant_id is not None:
            if header_raw:
                try:
                    header_tenant_id = uuid.UUID(header_raw.strip())
                    if header_tenant_id != auth_tenant_id:
                        return _TENANT_MISMATCH_RESPONSE
                except ValueError:
                    logger.warning("invalid_tenant_id_header", value=header_raw)

            tenant_id = auth_tenant_id

            # Validate tenant exists and is active (belt-and-suspenders)
            async with async_session() as session:
                stmt = select(Tenant).where(Tenant.id == tenant_id)
                result = await session.execute(stmt)
                tenant = result.scalar_one_or_none()

            if tenant is None:
                return Response(
                    status_code=403,
                    content='{"detail":"Tenant from authentication not found","error_code":"TENANT_NOT_FOUND"}',
                    media_type="application/json",
                )
            if tenant.status != "active":
                return Response(
                    status_code=403,
                    content=f'{{"detail":"Tenant account is {tenant.status}","error_code":"TENANT_{tenant.status.upper()}"}}',
                    media_type="application/json",
                )

            set_tenant(tenant_id)
            set_asserted_tenant(tenant_id)

            response = await call_next(request)
            headers = MutableHeaders(response.headers)
            headers[TENANT_ID_HEADER] = str(tenant_id)
            return response

        # ── Unauthenticated path (fall back to header) ────────────────────
        if header_raw:
            try:
                tenant_id = uuid.UUID(header_raw.strip())
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
                    logger.warning("tenant_not_active", tenant_id=str(tenant_id), status=tenant.status)
                    return Response(
                        status_code=403,
                        content=f'{{"detail":"Tenant account is {tenant.status}","error_code":"TENANT_{tenant.status.upper()}"}}',
                        media_type="application/json",
                    )

                set_tenant(tenant_id)
            except ValueError:
                logger.warning("invalid_tenant_id_header", value=header_raw)

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
