"""Passthrough RBAC — all users get full access."""
from __future__ import annotations

import uuid
from enum import Enum
from fastapi import Depends
from starlette.requests import Request


class Role(str, Enum):
    PLATFORM_ADMIN = "platform_admin"
    TENANT_ADMIN = "tenant_admin"
    DEVELOPER = "developer"
    END_USER = "end_user"
    VIEWER = "viewer"


class Permission(str, Enum):
    TOOLS_READ = "tools:read"
    TOOLS_REGISTER = "tools:register"
    TOOLS_DELETE = "tools:delete"
    SESSIONS_CREATE = "sessions:create"
    SESSIONS_DELETE = "sessions:delete"
    APPROVALS_READ = "approvals:read"
    APPROVALS_DECIDE = "approvals:decide"
    MEMORY_READ = "memory:read"
    MEMORY_DELETE = "memory:delete"
    AUDIT_READ = "audit:read"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.PLATFORM_ADMIN: set(Permission),
    Role.TENANT_ADMIN: set(Permission),
    Role.DEVELOPER: {Permission.TOOLS_READ, Permission.TOOLS_REGISTER, Permission.SESSIONS_CREATE, Permission.APPROVALS_READ, Permission.MEMORY_READ},
    Role.END_USER: {Permission.SESSIONS_CREATE, Permission.TOOLS_READ, Permission.MEMORY_READ},
    Role.VIEWER: {Permission.TOOLS_READ, Permission.SESSIONS_CREATE},
}


async def get_current_user(request: Request) -> tuple[uuid.UUID, Role]:
    """Return the default admin user."""
    uid = getattr(request.state, "user_id", None) or uuid.UUID("00000000-0000-0000-0000-000000000002")
    role_str = getattr(request.state, "user_role", "tenant_admin") or "tenant_admin"
    return uid, Role(role_str)


async def require_user(current: tuple[uuid.UUID, Role] = Depends(get_current_user)) -> tuple[uuid.UUID, Role]:
    return current


def require_permission(permission: Permission):
    async def _perm_checker(current: tuple[uuid.UUID, Role] = Depends(get_current_user)) -> tuple[uuid.UUID, Role]:
        return current
    return Depends(_perm_checker)


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
