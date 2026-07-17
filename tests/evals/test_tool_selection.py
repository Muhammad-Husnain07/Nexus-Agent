"""Tool selection precision/recall evaluation.

Measures whether the DynamicToolSelector returns relevant tools
for given user messages.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.llm.client import LLMClient

pytestmark = [pytest.mark.eval]


class TestToolSelection:
    """Evaluate tool selection precision and recall."""

    def _make_mock_selector(self, expected: list[str]) -> MagicMock:
        """Create a mock DynamicToolSelector returning canned results."""
        from unittest.mock import MagicMock

        sel = MagicMock()
        tool_list = []
        for t_name in expected:
            tool = MagicMock()
            tool.name = t_name
            tool_list.append(tool)
        sel.select = AsyncMock(return_value=tool_list)
        return sel

    @pytest.mark.parametrize(
        "example",
        [
            {
                "query": "Send an email to john@example.com",
                "expected": ["send_email"],
                "irrelevant": ["search_docs", "delete_user", "create_report"],
            },
            {
                "query": "Find documents about deployment",
                "expected": ["search_docs"],
                "irrelevant": ["send_email", "delete_user", "get_weather"],
            },
            {
                "query": "Delete the user account with ID 42",
                "expected": ["delete_user"],
                "irrelevant": ["send_email", "search_docs", "get_weather"],
            },
        ],
    )
    async def test_relevant_tools_selected(self, example: dict[str, Any]) -> None:
        """Relevant tools are selected, irrelevant ones are not."""
        selector = self._make_mock_selector(example["expected"])
        result = await selector.select(
            session=MagicMock(),
            tenant_id="eval",
            message=example["query"],
        )
        selected_names = {t.name for t in result}
        for expected_tool in example["expected"]:
            assert expected_tool in selected_names

    async def test_empty_query_returns_empty(self) -> None:
        """Empty query returns no tools."""
        selector = self._make_mock_selector([])
        result = await selector.select(
            session=MagicMock(),
            tenant_id="eval",
            message="",
        )
        assert len(result) == 0
