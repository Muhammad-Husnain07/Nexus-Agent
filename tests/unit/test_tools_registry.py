"""Unit tests for ToolRegistry — CRUD and semantic search."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.db.models.tool import Tool
from nexus.tools.registry import EMBEDDING_MODEL, ToolRegistry
from nexus.tools.schemas import ToolCreate, ToolUpdate


class _MockAsyncSession:
    """AsyncSession mock that sets ORM defaults on flush."""

    def __init__(self) -> None:
        self._added: list[object] = []
        self.add = MagicMock(side_effect=self._on_add)
        self.flush = AsyncMock(side_effect=self._on_flush)
        self.execute = AsyncMock()

    def _on_add(self, obj: object) -> None:
        self._added.append(obj)

    async def _on_flush(self) -> None:
        now = datetime.now(UTC)
        for obj in self._added:
            if isinstance(obj, Tool):
                if obj.id is None:
                    obj.id = uuid.uuid4()
                if obj.created_at is None:
                    obj.created_at = now
                if obj.updated_at is None:
                    obj.updated_at = now


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _make_tool(**overrides: object) -> Tool:
    tool = Tool(tenant_id=uuid.uuid4(), name=overrides.get("name", "tool"))
    tool.id = uuid.uuid4()
    now = datetime.now(UTC)
    tool.created_at = overrides.get("created_at", now)  # type: ignore[assignment]
    tool.updated_at = overrides.get("updated_at", now)  # type: ignore[assignment]
    tool.description = ""
    tool.purpose = ""
    tool.endpoint_url = ""
    tool.http_method = "GET"
    tool.auth_type = "none"
    tool.auth_ref = ""
    tool.input_schema = {}
    tool.output_schema = {}
    tool.validation_rules = {}
    tool.examples = []
    tool.tags = []
    tool.category = "general"
    tool.requires_approval = False
    tool.risk_level = "low"
    tool.enabled = True
    tool.version = 1
    tool.embedding = None
    for k, v in overrides.items():
        if k not in ("created_at", "updated_at"):
            setattr(tool, k, v)
    return tool


class _AsyncIter:
    """Utility to make a list async-iterable for ``async for`` loops."""

    def __init__(self, items: list) -> None:
        self._it = iter(items)

    def __aiter__(self) -> _AsyncIter:
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None


class TestRegister:
    @patch("nexus.tools.registry.LLMClient.embed")
    async def test_register_creates_tool(
        self,
        mock_embed: AsyncMock,
        registry: ToolRegistry,
        tenant_id: uuid.UUID,
    ) -> None:
        mock_embed.return_value = [[0.1, 0.2, 0.3]]
        data = ToolCreate(
            name="math-tool",
            description="Performs arithmetic",
            purpose="Add, subtract, multiply",
            tags=["math", "calc"],
        )

        session = _MockAsyncSession()
        result = await registry.register(session, tenant_id, data)

        assert result.name == "math-tool"
        assert result.version == 1
        assert result.embedding == [0.1, 0.2, 0.3]
        assert len(session._added) == 1
        assert session.flush.await_count == 2

    @patch("nexus.tools.registry.LLMClient.embed")
    async def test_register_generates_embedding(
        self,
        mock_embed: AsyncMock,
        registry: ToolRegistry,
        tenant_id: uuid.UUID,
    ) -> None:
        mock_embed.return_value = [[0.5, 0.5]]
        data = ToolCreate(name="test", description="desc", purpose="purp")

        session = _MockAsyncSession()
        await registry.register(session, tenant_id, data)

        mock_embed.assert_awaited_once_with(EMBEDDING_MODEL, ["test: desc. purp. tags: "])

    @patch("nexus.tools.registry.LLMClient.embed")
    async def test_register_handles_embedding_failure(
        self,
        mock_embed: AsyncMock,
        registry: ToolRegistry,
        tenant_id: uuid.UUID,
    ) -> None:
        mock_embed.side_effect = RuntimeError("API down")
        data = ToolCreate(name="resilient", description="desc")

        session = _MockAsyncSession()
        result = await registry.register(session, tenant_id, data)
        assert result.name == "resilient"
        assert result.embedding == []


class TestUpdate:
    @patch("nexus.tools.registry.ToolRegistry._get_model")
    @patch("nexus.tools.registry.LLMClient.embed")
    async def test_update_increments_version(
        self,
        mock_embed: AsyncMock,
        mock_get: AsyncMock,
        registry: ToolRegistry,
        tenant_id: uuid.UUID,
    ) -> None:
        mock_embed.return_value = [[0.1, 0.2]]
        tool = _make_tool(version=1)
        mock_get.return_value = tool

        session = _MockAsyncSession()
        result = await registry.update(
            session, tenant_id, uuid.uuid4(), ToolUpdate(description="updated")
        )

        assert result is not None
        assert result.version == 2

    @patch("nexus.tools.registry.ToolRegistry._get_model")
    @patch("nexus.tools.registry.LLMClient.embed")
    async def test_update_returns_none_if_not_found(
        self,
        mock_embed: AsyncMock,
        mock_get: AsyncMock,
        registry: ToolRegistry,
        tenant_id: uuid.UUID,
    ) -> None:
        mock_get.return_value = None

        session = _MockAsyncSession()
        result = await registry.update(session, tenant_id, uuid.uuid4(), ToolUpdate(name="new"))
        assert result is None


class TestDeregister:
    @patch("nexus.tools.registry.ToolRegistry._get_model")
    async def test_deregister_sets_enabled_false(
        self,
        mock_get: AsyncMock,
        registry: ToolRegistry,
        tenant_id: uuid.UUID,
    ) -> None:
        tool = _make_tool()
        mock_get.return_value = tool

        session = _MockAsyncSession()
        result = await registry.deregister(session, tenant_id, uuid.uuid4())

        assert result is True
        assert tool.enabled is False


class TestList:
    async def test_list_returns_paginated_results(
        self,
        registry: ToolRegistry,
        tenant_id: uuid.UUID,
    ) -> None:
        session = _MockAsyncSession()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        tool = _make_tool(name="tool", tenant_id=tenant_id)
        scalars_mock = AsyncMock()
        scalars_mock.all.return_value = [tool]
        list_result = MagicMock()
        list_result.scalars.return_value = scalars_mock

        session.execute.side_effect = [count_result, list_result]

        result = await registry.list(session, tenant_id)
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].name == "tool"


class TestSearchSemantic:
    @patch("nexus.tools.registry.LLMClient.embed")
    async def test_search_returns_ranked_results(
        self,
        mock_embed: AsyncMock,
        registry: ToolRegistry,
        tenant_id: uuid.UUID,
    ) -> None:
        mock_embed.return_value = [[0.9, 0.1]]
        tool_id = uuid.uuid4()
        session = _MockAsyncSession()

        row = MagicMock()
        row.__getitem__ = lambda self, i: [tool_id, 0.1][i]  # type: ignore[method-assign,return-value]

        tool = _make_tool(id=tool_id, name="found-tool", tenant_id=tenant_id)
        scalars_mock = AsyncMock()
        scalars_mock.all.return_value = [tool]
        lookup_result = MagicMock()
        lookup_result.scalars.return_value = scalars_mock

        session.execute.side_effect = [
            _AsyncIter([row]),
            lookup_result,
        ]

        results = await registry.search_semantic(session, tenant_id, "find math tools")
        assert len(results) == 1
        assert results[0].tool.name == "found-tool"
        assert results[0].score > 0
