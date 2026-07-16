"""Admin API — tenant management, quotas, users, audit log.

All endpoints require ``tenant_admin`` role.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from nexus.api.dependencies import SessionDep
from nexus.db.models.audit import AuditLog
from nexus.db.models.tenant import Tenant
from nexus.db.models.user import User
from nexus.db.repositories.base import GenericRepository
from nexus.errors import ForbiddenError
from nexus.security.rbac import (
    Role,
    require_user,
)

logger = structlog.get_logger("nexus.api.admin")

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


async def _require_admin(
    current: tuple[uuid.UUID, Role] = Depends(require_user),
) -> None:
    """Dependency: require tenant_admin role."""
    _uid, role = current
    if role != Role.TENANT_ADMIN:
        raise ForbiddenError("Admin access required")


# ── Tenants ─────────────────────────────────────────────────────────────────


@router.get("/tenants", dependencies=[Depends(_require_admin)])
async def list_tenants(
    session: SessionDep,
    status: str | None = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """List all tenants (admin only)."""
    stmt = select(Tenant).order_by(Tenant.created_at.desc())
    if status:
        stmt = stmt.where(Tenant.status == status)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(stmt)
    tenants = result.scalars().all()
    return [_tenant_to_dict(t) for t in tenants]


@router.get("/tenants/{tenant_id}", dependencies=[Depends(_require_admin)])
async def get_tenant_detail(
    tenant_id: uuid.UUID,
    session: SessionDep,
) -> dict[str, Any]:
    """Get tenant details including current usage counts."""
    repo = GenericRepository(session, Tenant)
    tenant = await repo.get(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    result = _tenant_to_dict(tenant)

    # Usage counts
    user_count = await session.scalar(select(User).where(User.tenant_id == tenant_id))
    result["usage"] = {"user_count": user_count or 0}
    return result


@router.patch("/tenants/{tenant_id}", dependencies=[Depends(_require_admin)])
async def update_tenant(
    tenant_id: uuid.UUID,
    body: dict[str, Any],
    session: SessionDep,
) -> dict[str, Any]:
    """Update tenant settings, status, or quotas."""
    repo = GenericRepository(session, Tenant)
    tenant = await repo.get(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if "status" in body:
        tenant.status = body["status"]
    if "settings" in body:
        current = dict(tenant.settings or {})
        current.update(body["settings"])
        tenant.settings = current
    if "name" in body:
        tenant.name = body["name"]

    await session.flush()
    await session.commit()
    return _tenant_to_dict(tenant)


# ── Users ───────────────────────────────────────────────────────────────────


@router.get("/tenants/{tenant_id}/users", dependencies=[Depends(_require_admin)])
async def list_users(
    tenant_id: uuid.UUID,
    session: SessionDep,
    role: str | None = Query(None, description="Filter by role"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """List users in a tenant."""
    stmt = select(User).where(User.tenant_id == tenant_id)
    if role:
        stmt = stmt.where(User.role == role)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(stmt)
    users = result.scalars().all()
    return [_user_to_dict(u) for u in users]


@router.post("/tenants/{tenant_id}/users", status_code=201, dependencies=[Depends(_require_admin)])
async def create_user(
    tenant_id: uuid.UUID,
    body: dict[str, Any],
    session: SessionDep,
) -> dict[str, Any]:
    """Create a new user in a tenant."""
    repo = GenericRepository(session, User)
    user = await repo.create(
        tenant_id=tenant_id,
        email=body.get("email", ""),
        external_id=body.get("external_id"),
        role=body.get("role", "end_user"),
    )
    await session.commit()
    return _user_to_dict(user)


@router.patch("/users/{user_id}", dependencies=[Depends(_require_admin)])
async def update_user(
    user_id: uuid.UUID,
    body: dict[str, Any],
    session: SessionDep,
) -> dict[str, Any]:
    """Update a user's role or other fields."""
    repo = GenericRepository(session, User)
    user = await repo.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if "role" in body:
        try:
            Role(body["role"])
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role: {body['role']}") from None
        user.role = body["role"]
    if "email" in body:
        user.email = body["email"]

    await session.flush()
    await session.commit()
    return _user_to_dict(user)


# ── Audit Log ───────────────────────────────────────────────────────────────


@router.get("/audit-log", dependencies=[Depends(_require_admin)])
async def list_audit_log(
    session: SessionDep,
    tenant_id: Annotated[uuid.UUID | None, Query(description="Filter by tenant")] = None,
    action: Annotated[str | None, Query(description="Filter by action type")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    """List audit log entries."""
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if tenant_id:
        stmt = stmt.where(AuditLog.tenant_id == tenant_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(stmt)
    entries = result.scalars().all()
    return [_audit_to_dict(e) for e in entries]


# ── Helpers ─────────────────────────────────────────────────────────────────


def _tenant_to_dict(tenant: Tenant) -> dict[str, Any]:
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "status": tenant.status,
        "settings": tenant.settings,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
    }


def _user_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "email": user.email,
        "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _audit_to_dict(entry: AuditLog) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "tenant_id": str(entry.tenant_id),
        "action": entry.action,
        "actor_id": str(entry.actor_id) if entry.actor_id else None,
        "target_type": entry.target_type,
        "target_id": str(entry.target_id) if entry.target_id else None,
        "details": entry.details,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }
