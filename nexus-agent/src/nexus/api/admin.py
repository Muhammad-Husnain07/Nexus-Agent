"""Admin API — tenant management, quotas, users, audit log.

All endpoints require ``tenant_admin`` or ``platform_admin`` role.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from nexus.api.dependencies import SessionDep
from nexus.db.models.audit import AuditLog
from nexus.db.models.tenant import Tenant
from nexus.db.models.user import ApiKey, User
from nexus.db.repositories.base import GenericRepository
from nexus.errors import ForbiddenError
from nexus.security.auth import generate_api_key, hash_api_key
from nexus.security.rbac import (
    Role,
    require_user,
)

logger = structlog.get_logger("nexus.api.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


async def _require_platform_admin(
    current: tuple[uuid.UUID, Role] = Depends(require_user),
) -> None:
    """Dependency: require platform_admin role (cross-tenant operations)."""
    _uid, role = current
    if role != Role.PLATFORM_ADMIN:
        raise ForbiddenError("Platform admin access required")


async def _require_tenant_admin(
    current: tuple[uuid.UUID, Role] = Depends(require_user),
) -> tuple[uuid.UUID, Role]:
    """Dependency: require tenant_admin or platform_admin role."""
    _uid, role = current
    if role not in (Role.TENANT_ADMIN, Role.PLATFORM_ADMIN):
        raise ForbiddenError("Admin access required")
    return current


async def _ensure_same_tenant(
    tenant_id: uuid.UUID,
    current: tuple[uuid.UUID, Role] = Depends(_require_tenant_admin),
    request: Request = None,
) -> None:
    """Ensure the caller manages their own tenant, unless platform_admin."""
    _uid, role = current
    if role == Role.PLATFORM_ADMIN:
        return
    caller_tenant_id = getattr(request.state, "tenant_id", None)
    if caller_tenant_id is None or caller_tenant_id != tenant_id:
        raise ForbiddenError("You can only access your own tenant's resources")


# ── Tenants ─────────────────────────────────────────────────────────────────


@router.get("/tenants", dependencies=[Depends(_require_platform_admin)])
async def list_tenants(
    session: SessionDep,
    status: str | None = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """List all tenants (platform admin only)."""
    stmt = select(Tenant).order_by(Tenant.created_at.desc())
    if status:
        stmt = stmt.where(Tenant.status == status)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(stmt)
    tenants = result.scalars().all()
    return [_tenant_to_dict(t) for t in tenants]


@router.get("/tenants/{tenant_id}", dependencies=[Depends(_ensure_same_tenant)])
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


@router.patch("/tenants/{tenant_id}", dependencies=[Depends(_ensure_same_tenant)])
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


@router.post("/tenants", status_code=201, dependencies=[Depends(_require_platform_admin)])
async def create_tenant(
    body: dict[str, Any],
    session: SessionDep,
) -> dict[str, Any]:
    """Create a new tenant (platform admin only). Validates unique slug."""
    slug = body.get("slug", "")
    if not slug:
        raise HTTPException(status_code=400, detail="slug is required")
    existing = await session.execute(select(Tenant).where(Tenant.slug == slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Tenant with slug '{slug}' already exists")

    repo = GenericRepository(session, Tenant)
    tenant = await repo.create(
        name=body.get("name", slug),
        slug=slug,
        status=body.get("status", "active"),
        settings=body.get("settings", {}),
    )
    await session.commit()
    return _tenant_to_dict(tenant)


# ── API Keys ─────────────────────────────────────────────────────────────


@router.get("/tenants/{tenant_id}/api-keys", dependencies=[Depends(_ensure_same_tenant)])
async def list_api_keys(
    tenant_id: uuid.UUID,
    session: SessionDep,
) -> list[dict[str, Any]]:
    """List API keys for a tenant."""
    stmt = select(ApiKey).where(ApiKey.tenant_id == tenant_id)
    result = await session.execute(stmt)
    keys = result.scalars().all()
    return [
        {
            "id": str(k.id),
            "label": k.label,
            "scopes": k.scopes,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        }
        for k in keys
    ]


@router.post("/tenants/{tenant_id}/api-keys", status_code=201, dependencies=[Depends(_ensure_same_tenant)])
async def create_api_key(
    tenant_id: uuid.UUID,
    body: dict[str, Any],
    session: SessionDep,
) -> dict[str, str]:
    """Generate a new API key. Returns the plaintext key ONCE."""
    raw_key = generate_api_key()
    key_hash = await hash_api_key(raw_key)
    repo = GenericRepository(session, ApiKey)
    api_key = await repo.create(
        tenant_id=tenant_id,
        key_hash=key_hash,
        label=body.get("label", ""),
        scopes=body.get("scopes", []),
        role_hint=body.get("role_hint", "end_user"),
    )
    await session.commit()
    return {
        "id": str(api_key.id),
        "plaintext_key": raw_key,
        "label": api_key.label or "",
    }


@router.delete("/tenants/{tenant_id}/api-keys/{key_id}", status_code=204, dependencies=[Depends(_ensure_same_tenant)])
async def delete_api_key(
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
    session: SessionDep,
) -> None:
    """Revoke (delete) an API key."""
    repo = GenericRepository(session, ApiKey)
    deleted = await repo.delete(key_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="API key not found")


# ── Users ───────────────────────────────────────────────────────────────────


@router.get("/tenants/{tenant_id}/users", dependencies=[Depends(_ensure_same_tenant)])
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


@router.post("/tenants/{tenant_id}/users", status_code=201, dependencies=[Depends(_ensure_same_tenant)])
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


@router.patch("/users/{user_id}", dependencies=[Depends(_require_tenant_admin)])
async def update_user(
    user_id: uuid.UUID,
    body: dict[str, Any],
    session: SessionDep,
    request: Request,
) -> dict[str, Any]:
    """Update a user's role or other fields."""
    repo = GenericRepository(session, User)
    user = await repo.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Ensure caller can update users in this tenant
    caller_tenant = getattr(request.state, "tenant_id", None)
    if caller_tenant is not None and user.tenant_id != caller_tenant:
        raise ForbiddenError("You can only update users in your own tenant")

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


@router.get("/audit-log", dependencies=[Depends(_require_platform_admin)])
async def list_audit_log(
    session: SessionDep,
    tenant_id: Annotated[uuid.UUID | None, Query(description="Filter by tenant")] = None,
    action: Annotated[str | None, Query(description="Filter by action type")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    """List audit log entries (platform admin only — cross-tenant)."""
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
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "payload": entry.payload,
        "ip": entry.ip,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }
