"""Tests for the DynamicToolSelector — tool discovery and ranking."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.registry import ToolRegistry
from nexus.tools.schemas import ToolRead


class TestDynamicToolSelector:
    """Verify tool selection with semantic search and LLM reranking."""

    @pytest.fixture
    def mock_registry(self) -> MagicMock:
        registry = MagicMock(spec=ToolRegistry)
        registry.search_semantic = AsyncMock(return_value=[])
        return registry

    @pytest.fixture
    def mock_llm(self) -> MagicMock:
        llm = MagicMock()
        llm.embed = AsyncMock(return_value=[[0.1] * 768])
        llm.complete = AsyncMock()
        return llm

    @pytest.fixture
    def selector(self, mock_registry: MagicMock, mock_llm: MagicMock) -> DynamicToolSelector:
        return DynamicToolSelector(registry=mock_registry, llm_client=mock_llm, cache=None)

    async def test_select_with_empty_message(
        self, selector: DynamicToolSelector
    ) -> None:
        session = MagicMock()
        result = await selector.select(session, uuid.uuid4(), "")
        assert result == []

    async def test_select_calls_semantic_search(
        self, selector: DynamicToolSelector, mock_registry: MagicMock
    ) -> None:
        session = MagicMock()
        tid = uuid.uuid4()
        await selector.select(session, tid, "send email")
        mock_registry.search_semantic.assert_awaited_once()

    async def test_select_with_context(
        self, selector: DynamicToolSelector, mock_registry: MagicMock
    ) -> None:
        session = MagicMock()
        tid = uuid.uuid4()
        await selector.select(session, tid, "send it", context="to john")
        mock_registry.search_semantic.assert_awaited_once()

    async def test_llm_rerank_small_list_passthrough(
        self, selector: DynamicToolSelector, mock_registry: MagicMock
    ) -> None:
        tools = [
            ToolRead(
                id=uuid.uuid4(), tenant_id=uuid.uuid4(), name="send_email",
                description="Sends email", purpose="", endpoint_url="",
                http_method="POST", auth_type="none", auth_ref="",
                input_schema={}, output_schema={}, validation_rules={},
                examples=[], tags=[], category="", requires_approval=False,
                risk_level="low", enabled=True, version=1,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
            ),
        ]
        from unittest.mock import MagicMock

        mock_result = MagicMock()
        mock_result.tool = tools[0]
        mock_result.score = 0.9

        mock_registry.search_semantic.return_value = [mock_result]
        session = MagicMock()
        result = await selector.select(session, uuid.uuid4(), "send email", k=5)
        assert len(result) == 1
        assert result[0].name == "send_email"

    async def test_rerank_reorders(
        self, selector: DynamicToolSelector, mock_llm: MagicMock
    ) -> None:
        mock_llm.complete.return_value.content = "tool_b, tool_a"
        tool_a = ToolRead(
            id=uuid.uuid4(), tenant_id=uuid.uuid4(), name="tool_a",
            description="Tool A", purpose="", endpoint_url="",
            http_method="GET", auth_type="none", auth_ref="",
            input_schema={}, output_schema={}, validation_rules={},
            examples=[], tags=[], category="", requires_approval=False,
            risk_level="low", enabled=True, version=1,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        tool_b = ToolRead(
            id=uuid.uuid4(), tenant_id=uuid.uuid4(), name="tool_b",
            description="Tool B", purpose="", endpoint_url="",
            http_method="GET", auth_type="none", auth_ref="",
            input_schema={}, output_schema={}, validation_rules={},
            examples=[], tags=[], category="", requires_approval=False,
            risk_level="low", enabled=True, version=1,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        ranked = await selector._llm_rerank("message", [tool_a, tool_b])
        assert ranked[0].name == "tool_b"
        assert ranked[1].name == "tool_a"
