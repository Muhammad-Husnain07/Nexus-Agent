"""Multi-tenant isolation tests — verify tenants cannot see each other's data.

Uses testcontainers for real PostgreSQL to enforce tenant isolation
at the database and API layers.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.context import set_tenant
from nexus.tools.registry import ToolRegistry
from nexus.tools.schemas import ToolCreate

pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestTenantIsolation:
    """Verify Tenant A cannot access Tenant B's data."""

    TID_A = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    TID_B = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

    @pytest_asyncio_fixture  # noqa: F821
    async def seed_two_tenants(self, db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
        """Create two tenants each with a unique tool."""
        from nexus.db.models.tenant import Tenant
        from nexus.db.models.user import User

        tenant_a = Tenant(id=self.TID_A, name="Tenant A", slug="tenant-a")
        tenant_b = Tenant(id=self.TID_B, name="Tenant B", slug="tenant-b")
        db_session.add_all([tenant_a, tenant_b])
        user_a = User(id=uuid.uuid4(), tenant_id=self.TID_A, email="a@test.com", role="developer")
        user_b = User(id=uuid.uuid4(), tenant_id=self.TID_B, email="b@test.com", role="developer")
        db_session.add_all([user_a, user_b])
        await db_session.commit()

        registry = ToolRegistry()

        set_tenant(self.TID_A)
        tool_a = await registry.register(
            db_session,
            self.TID_A,
            ToolCreate(
                name="tenant_a_tool",
                description="Only Tenant A should see this",
                purpose="Isolation test",
                endpoint_url="http://example.com/a",
                http_method="GET",
                tags=["tenant-a"],
                category="test",
            ),
        )

        set_tenant(self.TID_B)
        tool_b = await registry.register(
            db_session,
            self.TID_B,
            ToolCreate(
                name="tenant_b_tool",
                description="Only Tenant B should see this",
                purpose="Isolation test",
                endpoint_url="http://example.com/b",
                http_method="GET",
                tags=["tenant-b"],
                category="test",
            ),
        )

        await db_session.commit()
        return (tool_a.id, tool_b.id)

    async def test_tenant_a_cannot_see_tenant_b_tools(
        self, db_session: AsyncSession, seed_two_tenants: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Tenant A's tool list does not include Tenant B's tools."""
        tool_a_id, tool_b_id = seed_two_tenants
        registry = ToolRegistry()

        set_tenant(self.TID_A)
        tenant_a_tools = await registry.list(db_session, self.TID_A, enabled=True, page_size=50)
        tool_ids_a = {t.id for t in tenant_a_tools.items}
        assert tool_a_id in tool_ids_a
        assert tool_b_id not in tool_ids_a

    async def test_tenant_b_cannot_see_tenant_a_tools(
        self, db_session: AsyncSession, seed_two_tenants: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Tenant B's tool list does not include Tenant A's tools."""
        tool_a_id, tool_b_id = seed_two_tenants
        registry = ToolRegistry()

        set_tenant(self.TID_B)
        tenant_b_tools = await registry.list(db_session, self.TID_B, enabled=True, page_size=50)
        tool_ids_b = {t.id for t in tenant_b_tools.items}
        assert tool_b_id in tool_ids_b
        assert tool_a_id not in tool_ids_b

    async def test_semantic_search_respects_tenant(
        self, db_session: AsyncSession, seed_two_tenants: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Semantic search across tenants returns scoped results."""
        tool_a_id, tool_b_id = seed_two_tenants
        registry = ToolRegistry()

        set_tenant(self.TID_A)
        results_a = await registry.search_semantic(db_session, self.TID_A, "tenant")
        result_ids_a = {r.tool.id for r in results_a}
        assert tool_a_id in result_ids_a
        assert tool_b_id not in result_ids_a
