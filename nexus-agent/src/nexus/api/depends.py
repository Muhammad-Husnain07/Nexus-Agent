"""Minimal FastAPI dependencies — tenant, user — without circular imports.

These lightweight dependencies only import from ``fastapi`` and
``nexus.db.context``, making them safe to import from any router
module without creating circular dependencies.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request

from nexus.db.context import get_tenant


async def _current_tenant(request: Request) -> uuid.UUID | None:
    """Return the tenant ID from middleware-set context or request state."""
    tid = getattr(request.state, "tenant_id", None)
    if tid is not None:
        return uuid.UUID(tid) if isinstance(tid, str) else tid
    return get_tenant()


async def _current_user(request: Request) -> uuid.UUID | None:
    """Return the authenticated user ID from request state."""
    uid = getattr(request.state, "user_id", None)
    if uid is not None:
        return uuid.UUID(uid) if isinstance(uid, str) else uid
    return None


TenantDep = Annotated[uuid.UUID | None, Depends(_current_tenant)]
"""FastAPI dependency that resolves the current tenant ID."""

UserDep = Annotated[uuid.UUID | None, Depends(_current_user)]
"""FastAPI dependency that resolves the current user ID."""
