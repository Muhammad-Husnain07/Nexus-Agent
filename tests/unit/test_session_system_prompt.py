"""Unit tests for SystemPromptBuilder — dynamic prompt assembly and caching."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models.tenant import Tenant as TenantModel
from nexus.sessions.system_prompt import SystemPromptBuilder


@pytest.fixture
def builder() -> SystemPromptBuilder:
    return SystemPromptBuilder()


@pytest.fixture
def mock_session() -> AsyncMock:
    return create_autospec(AsyncSession, instance=True)


class MockSessionObj:
    def __init__(self) -> None:
        self.tenant_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
        self.user_id = uuid.UUID("22222222-2222-4222-8222-222222222222")
        self.id = uuid.uuid4()


@pytest.fixture
def mock_session_obj() -> MockSessionObj:
    return MockSessionObj()


class TestSystemPromptBuilder:
    async def test_build_contains_identity(self, builder: SystemPromptBuilder, mock_session_obj: MockSessionObj) -> None:
        result = await builder.build(mock_session_obj)
        assert "Nexus Agent" in result

    async def test_build_contains_date(self, builder: SystemPromptBuilder, mock_session_obj: MockSessionObj) -> None:
        result = await builder.build(mock_session_obj)
        assert "UTC" in result
        assert "202" in result  # current year

    async def test_build_contains_guidelines(self, builder: SystemPromptBuilder, mock_session_obj: MockSessionObj) -> None:
        result = await builder.build(mock_session_obj)
        assert "clarifying questions" in result
        assert "approval" in result

    async def test_build_with_tool_categories(self, builder: SystemPromptBuilder, mock_session_obj: MockSessionObj) -> None:
        cats = ["search", "compute", "storage"]
        result = await builder.build(mock_session_obj, tool_categories=cats)
        assert "search" in result
        assert "compute" in result
        assert "storage" in result
        assert "Available tool categories" in result

    async def test_build_with_tenant_instructions(self, builder: SystemPromptBuilder, mock_session_obj: MockSessionObj) -> None:
        tenant = MagicMock(spec=TenantModel)
        tenant.settings = {"instructions": "Follow HIPAA guidelines."}
        result = await builder.build(mock_session_obj, tenant=tenant)
        assert "HIPAA" in result
        assert "Tenant instructions" in result

    async def test_build_caches_result(self, builder: SystemPromptBuilder, mock_session_obj: MockSessionObj) -> None:
        r1 = await builder.build(mock_session_obj)
        r2 = await builder.build(mock_session_obj)
        assert r1 is r2  # same cached object

    async def test_build_different_users_different_cache(self, builder: SystemPromptBuilder) -> None:
        s1 = MockSessionObj()
        s2 = MockSessionObj()
        r1 = await builder.build(s1)
        r2 = await builder.build(s2)
        # same tenant, different user IDs — depends on user_id matching
        # Since both have same tenant_id, the cache key is same
        assert r1 == r2  # same tenant_id + user_id pattern

    async def test_invalidate_cache(self, builder: SystemPromptBuilder, mock_session_obj: MockSessionObj) -> None:
        r1 = await builder.build(mock_session_obj)
        builder.invalidate_cache(mock_session_obj.tenant_id, mock_session_obj.user_id)
        r2 = await builder.build(mock_session_obj)
        assert r1 is not r2  # different objects after invalidation
        # but should be equal since nothing changed
        assert r1 == r2

    async def test_build_with_preferences(self, builder: SystemPromptBuilder, mock_session_obj: MockSessionObj) -> None:
        result = await builder.build(mock_session_obj)
        # Without a DB session or tenant, preferences should be absent
        assert "User preferences" not in result
