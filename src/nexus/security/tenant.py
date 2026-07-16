"""Tenant resolution, validation, and context management.

Re-exports tenant utilities from the middleware and context layers so
that ``src/nexus/security/`` provides a single entry point for all
tenant-related functionality.
"""

from __future__ import annotations

import uuid

from nexus.db.context import get_tenant, reset_tenant, set_tenant
from nexus.db.models.tenant import Tenant
from nexus.middleware.tenant import TenantMiddleware

__all__ = [
    "TenantMiddleware",
    "get_tenant",
    "set_tenant",
    "reset_tenant",
    "Tenant",
]


async def validate_tenant_exists(tenant_id: uuid.UUID) -> Tenant | None:
    """Look up a tenant by ID and return it, or ``None`` if not found.

    This is a convenience wrapper around the DB query used by the
    ``TenantMiddleware`` so that other modules can validate tenant
    existence without reimplementing the query.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from nexus.db.base import async_session  # noqa: PLC0415

    async with async_session() as session:
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
