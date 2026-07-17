"""RBAC — role definitions, permission mapping, and enforcement."""

from __future__ import annotations

import uuid
from enum import Enum

from fastapi import Depends, Request
from sqlalchemy import select

from nexus.db.base import async_session
from nexus.db.models.user import User
from nexus.errors import ForbiddenError, UnauthorizedError

# ── Roles ───────────────────────────────────────────────────────────────────


class Role(str, Enum):  # noqa: UP042
    """RBAC roles available in the system."""

    TENANT_ADMIN = "tenant_admin"
    DEVELOPER = "developer"
    END_USER = "end_user"
    VIEWER = "viewer"


# ── Permissions ─────────────────────────────────────────────────────────────


class Permission(str, Enum):  # noqa: UP042
    """Fine-grained action permissions."""

    # Tools
    TOOLS_REGISTER = "tools:register"
    TOOLS_DELETE = "tools:delete"
    TOOLS_READ = "tools:read"
    # Sessions
    SESSIONS_READ_OWN = "sessions:read:own"
    SESSIONS_READ_ANY = "sessions:read:any"
    SESSIONS_DELETE = "sessions:delete"
    # Approvals
    APPROVALS_DECIDE = "approvals:decide"
    # Agent
    AGENTS_INVOKE = "agents:invoke"
    # Memory
    MEMORY_READ = "memory:read"
    MEMORY_DELETE = "memory:delete"
    # Audit
    AUDIT_READ = "audit:read"
    # Admin
    ADMIN_ACCESS = "admin:access"
    USER_MANAGE = "user:manage"


# ── Role → Permission mapping ───────────────────────────────────────────────

ROLE_PERMISSIONS: dict[Role, list[Permission]] = {
    Role.TENANT_ADMIN: [
        Permission.TOOLS_REGISTER,
        Permission.TOOLS_DELETE,
        Permission.TOOLS_READ,
        Permission.SESSIONS_READ_ANY,
        Permission.SESSIONS_DELETE,
        Permission.APPROVALS_DECIDE,
        Permission.AGENTS_INVOKE,
        Permission.MEMORY_READ,
        Permission.MEMORY_DELETE,
        Permission.AUDIT_READ,
        Permission.ADMIN_ACCESS,
        Permission.USER_MANAGE,
    ],
    Role.DEVELOPER: [
        Permission.TOOLS_REGISTER,
        Permission.TOOLS_DELETE,
        Permission.TOOLS_READ,
        Permission.SESSIONS_READ_OWN,
        Permission.APPROVALS_DECIDE,
        Permission.AGENTS_INVOKE,
        Permission.MEMORY_READ,
    ],
    Role.END_USER: [
        Permission.TOOLS_READ,
        Permission.SESSIONS_READ_OWN,
        Permission.AGENTS_INVOKE,
        Permission.MEMORY_READ,
    ],
    Role.VIEWER: [
        Permission.TOOLS_READ,
        Permission.SESSIONS_READ_OWN,
    ],
}


# ── Permission checker ──────────────────────────────────────────────────────


def _get_user_role(user: User) -> Role:
    """Map a User model's ``role`` string to a ``Role`` enum."""
    try:
        return Role(user.role)
    except ValueError:
        return Role.END_USER  # safe fallback


async def get_current_user(  # noqa: B008
    request: Request,
) -> tuple[uuid.UUID, Role] | None:
    """Resolve the current user ID and role from request state or DB.

    Returns:
        ``(user_id, role)`` tuple or ``None`` if anonymous.
    """
    uid = getattr(request.state, "user_id", None)
    role_str = getattr(request.state, "user_role", None)

    if uid is not None and role_str is not None:
        try:
            return uid, Role(role_str)
        except ValueError:
            pass

    # Fallback: load from DB
    if uid is not None:
        async with async_session() as session:
            stmt = select(User).where(User.id == uid)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user is not None:
                return user.id, _get_user_role(user)

    return None


async def require_user(
    current: tuple[uuid.UUID, Role] | None = Depends(get_current_user),
) -> tuple[uuid.UUID, Role]:
    """Require an authenticated user — raises 401 if anonymous."""
    if current is None:
        raise UnauthorizedError("Authentication required")
    return current


def require_permission(*permissions: Permission):
    """Factory: return a FastAPI dependency that checks for *permissions*.

    Usage::

        @router.post("/tools",
        ...           dependencies=[Depends(require_permission(Permission.TOOLS_REGISTER))])
        async def register_tool(...):
            ...

    The dependency loads the current user from the request state or the
    ``Authorization`` header, resolves their role, and checks that the
    role has **all** of the specified permissions.
    """

    async def _check(
        current: tuple[uuid.UUID, Role] = Depends(require_user),
    ) -> None:
        _uid, role = current
        allowed = ROLE_PERMISSIONS.get(role, [])
        for perm in permissions:
            if perm not in allowed:
                raise ForbiddenError(f"Role '{role.value}' lacks permission '{perm.value}'")

    return Depends(_check)
