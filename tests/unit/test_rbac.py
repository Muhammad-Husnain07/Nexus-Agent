"""Exhaustive RBAC tests — every role ↔ permission mapping verified."""

from __future__ import annotations

import pytest

from nexus.security.rbac import ROLE_PERMISSIONS, Permission, Role


class TestRolePermissionMapping:
    """Every role has exactly the expected permissions."""

    @pytest.mark.parametrize(
        "role,expected",
        [
            (
                Role.TENANT_ADMIN,
                {
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
                },
            ),
            (
                Role.DEVELOPER,
                {
                    Permission.TOOLS_REGISTER,
                    Permission.TOOLS_DELETE,
                    Permission.TOOLS_READ,
                    Permission.SESSIONS_READ_OWN,
                    Permission.APPROVALS_DECIDE,
                    Permission.AGENTS_INVOKE,
                    Permission.MEMORY_READ,
                },
            ),
            (
                Role.END_USER,
                {
                    Permission.TOOLS_READ,
                    Permission.SESSIONS_READ_OWN,
                    Permission.AGENTS_INVOKE,
                    Permission.MEMORY_READ,
                },
            ),
            (
                Role.VIEWER,
                {
                    Permission.TOOLS_READ,
                    Permission.SESSIONS_READ_OWN,
                },
            ),
        ],
    )
    def test_role_permissions(self, role: Role, expected: set[Permission]) -> None:
        assert set(ROLE_PERMISSIONS[role]) == expected

    def test_admin_includes_all_lower_roles(self) -> None:
        admin = set(ROLE_PERMISSIONS[Role.TENANT_ADMIN])
        dev = set(ROLE_PERMISSIONS[Role.DEVELOPER])
        user = set(ROLE_PERMISSIONS[Role.END_USER])
        viewer = set(ROLE_PERMISSIONS[Role.VIEWER])

        # Remove SESSIONS_READ_OWN from dev since ADMIN has SESSIONS_READ_ANY
        dev_effective = dev - {Permission.SESSIONS_READ_OWN}
        user_effective = user - {Permission.SESSIONS_READ_OWN}
        viewer_effective = viewer - {Permission.SESSIONS_READ_OWN}

        assert dev_effective.issubset(admin), "Admin should have all developer permissions"
        assert user_effective.issubset(admin), "Admin should have all end_user permissions"
        assert viewer_effective.issubset(admin), "Admin should have all viewer permissions"

    @pytest.mark.parametrize(
        "role,permission,should_have",
        [
            (Role.TENANT_ADMIN, Permission.TOOLS_REGISTER, True),
            (Role.DEVELOPER, Permission.TOOLS_REGISTER, True),
            (Role.END_USER, Permission.TOOLS_REGISTER, False),
            (Role.VIEWER, Permission.TOOLS_REGISTER, False),
            (Role.TENANT_ADMIN, Permission.ADMIN_ACCESS, True),
            (Role.DEVELOPER, Permission.ADMIN_ACCESS, False),
            (Role.END_USER, Permission.ADMIN_ACCESS, False),
            (Role.TENANT_ADMIN, Permission.APPROVALS_DECIDE, True),
            (Role.DEVELOPER, Permission.APPROVALS_DECIDE, True),
            (Role.END_USER, Permission.APPROVALS_DECIDE, False),
            (Role.VIEWER, Permission.APPROVALS_DECIDE, False),
            (Role.TENANT_ADMIN, Permission.SESSIONS_READ_ANY, True),
            (Role.DEVELOPER, Permission.SESSIONS_READ_ANY, False),
            (Role.END_USER, Permission.SESSIONS_READ_ANY, False),
            (Role.VIEWER, Permission.SESSIONS_READ_OWN, True),
            (Role.END_USER, Permission.AGENTS_INVOKE, True),
            (Role.VIEWER, Permission.AGENTS_INVOKE, False),
        ],
    )
    def test_specific_permission(
        self, role: Role, permission: Permission, should_have: bool
    ) -> None:
        has_perm = permission in ROLE_PERMISSIONS[role]
        assert has_perm == should_have


class TestRoleScopes:
    """Role-based tool scoping."""

    def test_admin_sees_only_own_tenant_tools(self) -> None:
        from nexus.security.scopes import filter_tools_by_role

        tools = [
            {"tenant_id": "aaa", "tenant_public": False},
            {"tenant_id": "bbb", "tenant_public": False},
        ]
        result = filter_tools_by_role(tools, Role.TENANT_ADMIN, "aaa")
        assert len(result) == 1
        assert result[0]["tenant_id"] == "aaa"

    def test_dev_sees_only_own_tenant_tools(self) -> None:
        from nexus.security.scopes import filter_tools_by_role

        tools = [
            {"tenant_id": "aaa", "tenant_public": False},
            {"tenant_id": "bbb", "tenant_public": True},
        ]
        result = filter_tools_by_role(tools, Role.DEVELOPER, "aaa")
        assert len(result) == 1

    def test_anonymous_sees_only_public_tools(self) -> None:
        from nexus.security.scopes import filter_tools_by_role

        tools = [
            {"tenant_id": "aaa", "tenant_public": False},
            {"tenant_id": "bbb", "tenant_public": True},
        ]
        result = filter_tools_by_role(tools, None, None)
        assert len(result) == 1
        assert result[0]["tenant_public"] is True
