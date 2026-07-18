"""Direct handler tests for tools/api.py — call route functions inline."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from nexus.tools.api import (
    delete_tool,
    get_tool,
    list_tools,
    search_tools,
    test_tool,
    update_tool,
)
from nexus.tools.schemas import ToolCreate, ToolRead, ToolUpdate


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_registry() -> MagicMock:
    return MagicMock()


@pytest.fixture
def tid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def tool_read(tid: uuid.UUID) -> ToolRead:
    return ToolRead(
        id=uuid.uuid4(), tenant_id=tid, name="echo", description="Test",
        purpose="Testing", endpoint_url="http://test/echo", http_method="POST",
        auth_type="none", auth_ref="", input_schema={}, output_schema={},
        validation_rules={}, examples=[], tags=["test"], category="utilities",
        requires_approval=False, risk_level="low", enabled=True, version=1,
        created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
    )


class TestToolsAPI:
    async def test_get_tool_found(self, mock_session: AsyncMock, mock_registry: MagicMock, tool_read: ToolRead) -> None:
        mock_registry.get = AsyncMock(return_value=tool_read)
        result = await get_tool(tool_read.id, mock_registry, mock_session, tool_read.tenant_id)
        assert result.id == tool_read.id

    async def test_get_tool_not_found(self, mock_session: AsyncMock, mock_registry: MagicMock) -> None:
        mock_registry.get = AsyncMock(return_value=None)
        with pytest.raises(HTTPException, match="Tool not found"):
            await get_tool(uuid.uuid4(), mock_registry, mock_session, uuid.uuid4())

    async def test_search_tools(self, mock_session: AsyncMock, mock_registry: MagicMock, tid: uuid.UUID) -> None:
        mock_registry.search_semantic = AsyncMock(return_value=[])
        result = await search_tools(mock_registry, mock_session, tid, q="test")
        assert result == []

    async def test_delete_success(self, mock_session: AsyncMock, mock_registry: MagicMock, tid: uuid.UUID) -> None:
        mock_registry.deregister = AsyncMock(return_value=True)
        await delete_tool(uuid.uuid4(), mock_registry, mock_session, tid)

    async def test_delete_not_found(self, mock_session: AsyncMock, mock_registry: MagicMock, tid: uuid.UUID) -> None:
        mock_registry.deregister = AsyncMock(return_value=False)
        with pytest.raises(HTTPException, match="Tool not found"):
            await delete_tool(uuid.uuid4(), mock_registry, mock_session, tid)

    async def test_update_not_found(self, mock_session: AsyncMock, mock_registry: MagicMock, tid: uuid.UUID) -> None:
        mock_registry.update = AsyncMock(return_value=None)
        with pytest.raises(HTTPException, match="Tool not found"):
            await update_tool(uuid.uuid4(), ToolUpdate(), mock_registry, mock_session, tid)

    async def test_list_tools(self, mock_session: AsyncMock, mock_registry: MagicMock, tid: uuid.UUID) -> None:
        from nexus.tools.schemas import ToolList
        mock_registry.list = AsyncMock(return_value=ToolList(items=[], total=0, page=1, page_size=20))
        result = await list_tools(mock_registry, mock_session, tid, tags=None, category=None, enabled=True, page=1, page_size=20)
        assert result.total == 0

    async def test_test_tool_not_found(self, mock_session: AsyncMock, mock_registry: MagicMock, tid: uuid.UUID) -> None:
        mock_registry.get = AsyncMock(return_value=None)
        with pytest.raises(HTTPException, match="Tool not found"):
            await test_tool(uuid.uuid4(), mock_registry, mock_session, tid)

    async def test_test_tool_missing_required(self, mock_session: AsyncMock, mock_registry: MagicMock, tool_read: ToolRead) -> None:
        tool_read.input_schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        mock_registry.get = AsyncMock(return_value=tool_read)
        with pytest.raises(HTTPException, match="Missing required field"):
            await test_tool(tool_read.id, mock_registry, mock_session, tool_read.tenant_id)
