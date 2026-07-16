"""Tool-level scoping — tenant_public flag and role-based visibility."""

from __future__ import annotations

from typing import Any

from nexus.security.rbac import ROLE_PERMISSIONS, Permission, Role


def can_register_tools(user_role: Role) -> bool:
    """Check if a role can register tools."""
    return Permission.TOOLS_REGISTER in ROLE_PERMISSIONS.get(user_role, [])


def can_delete_tools(user_role: Role) -> bool:
    """Check if a role can delete tools."""
    return Permission.TOOLS_DELETE in ROLE_PERMISSIONS.get(user_role, [])


def filter_tools_by_role(
    tools: list[dict[str, Any]],
    user_role: Role | None,
    user_tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """Filter a list of tools based on user role and visibility.

    Rules:
    - ``tenant_admin`` and ``developer`` see all tools in their tenant.
    - ``end_user`` and ``viewer`` see only ``tenant_public`` tools or
      tools they own.
    - If the user has no role (anonymous), only ``tenant_public`` tools
      with no tenant restriction are visible.
    - Cross-tenant tools (``tenant_public=True``) are visible to all
      authenticated users regardless of tenant.

    Args:
        tools: List of tool dicts (with ``tenant_public``, ``tenant_id`` keys).
        user_role: The user's role (``None`` for anonymous).
        user_tenant_id: The user's tenant ID (string).

    Returns:
        Filtered list of visible tools.
    """
    if user_role in (Role.TENANT_ADMIN, Role.DEVELOPER):
        # Admins and developers see all tools in their tenant
        if user_tenant_id is not None:
            return [t for t in tools if str(t.get("tenant_id", "")) == user_tenant_id]
        return list(tools)

    # End users, viewers, anonymous
    filtered: list[dict[str, Any]] = []
    for t in tools:
        is_public = t.get("tenant_public", False)
        if is_public or user_tenant_id and str(t.get("tenant_id", "")) == user_tenant_id:
            filtered.append(t)
    return filtered
