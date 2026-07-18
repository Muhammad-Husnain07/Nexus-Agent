"""Tool scoping tests — role-based visibility and filtering."""

from __future__ import annotations

import pytest

from nexus.security.rbac import Permission, Role
from nexus.security.scopes import (
    can_delete_tools,
    can_register_tools,
    filter_tools_by_role,
)


class TestCanRegisterTools:
    def test_admin_can_register(self) -> None:
        assert can_register_tools(Role.TENANT_ADMIN) is True

    def test_developer_can_register(self) -> None:
        assert can_register_tools(Role.DEVELOPER) is True

    def test_end_user_cannot_register(self) -> None:
        assert can_register_tools(Role.END_USER) is False

    def test_viewer_cannot_register(self) -> None:
        assert can_register_tools(Role.VIEWER) is False


class TestCanDeleteTools:
    def test_admin_can_delete(self) -> None:
        assert can_delete_tools(Role.TENANT_ADMIN) is True

    def test_developer_can_delete(self) -> None:
        assert can_delete_tools(Role.DEVELOPER) is True

    def test_end_user_cannot_delete(self) -> None:
        assert can_delete_tools(Role.END_USER) is False

    def test_viewer_cannot_delete(self) -> None:
        assert can_delete_tools(Role.VIEWER) is False


class TestFilterToolsByRole:
    def test_admin_sees_own_tenant(self) -> None:
        tools = [
            {"tenant_id": "aaa", "tenant_public": False},
            {"tenant_id": "bbb", "tenant_public": False},
        ]
        result = filter_tools_by_role(tools, Role.TENANT_ADMIN, "aaa")
        assert len(result) == 1
        assert result[0]["tenant_id"] == "aaa"

    def test_admin_sees_all_when_no_tenant_id(self) -> None:
        tools = [
            {"tenant_id": "aaa", "tenant_public": False},
            {"tenant_id": "bbb", "tenant_public": False},
        ]
        result = filter_tools_by_role(tools, Role.TENANT_ADMIN, None)
        assert len(result) == 2

    def test_developer_sees_own_tenant(self) -> None:
        tools = [
            {"tenant_id": "aaa", "tenant_public": False},
            {"tenant_id": "bbb", "tenant_public": True},
        ]
        result = filter_tools_by_role(tools, Role.DEVELOPER, "aaa")
        assert len(result) == 1
        assert result[0]["tenant_id"] == "aaa"

    def test_end_user_sees_public_and_own(self) -> None:
        tools = [
            {"tenant_id": "aaa", "tenant_public": False},
            {"tenant_id": "bbb", "tenant_public": True},
            {"tenant_id": "aaa", "tenant_public": True},
        ]
        result = filter_tools_by_role(tools, Role.END_USER, "aaa")
        assert len(result) == 3

    def test_viewer_sees_public_and_own(self) -> None:
        tools = [
            {"tenant_id": "aaa", "tenant_public": False, "name": "a-private"},
            {"tenant_id": "bbb", "tenant_public": True, "name": "b-public"},
        ]
        result = filter_tools_by_role(tools, Role.VIEWER, "aaa")
        assert len(result) == 2

    def test_anonymous_sees_only_public(self) -> None:
        tools = [
            {"tenant_id": "aaa", "tenant_public": False},
            {"tenant_id": "bbb", "tenant_public": True},
        ]
        result = filter_tools_by_role(tools, None, None)
        assert len(result) == 1
        assert result[0]["tenant_public"] is True

    def test_anonymous_without_tenant_id(self) -> None:
        tools = [
            {"tenant_id": "aaa", "tenant_public": True},
            {"tenant_id": "bbb", "tenant_public": False},
        ]
        result = filter_tools_by_role(tools, None, None)
        assert len(result) == 1
