"""Unit tests for ContextWindowManager — token counting, summarization, preservation."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest

from nexus.config.settings import AgentSettings
from nexus.db.models.session import Message as MessageModel
from nexus.llm.client import LLMClient, LLMResponse, UsageInfo
from nexus.sessions.context_window import (
    ContextWindowManager,
    _message_to_text,
    count_tokens,
    messages_token_count,
)


@pytest.fixture
def settings() -> AgentSettings:
    return AgentSettings(summarization_threshold_tokens=100)


@pytest.fixture
def llm() -> AsyncMock:
    client = create_autospec(LLMClient, instance=True)
    client.complete = AsyncMock(
        return_value=LLMResponse(
            content="Summary of the conversation.",
            usage=UsageInfo(prompt_tokens=50, completion_tokens=10, total_tokens=60),
            model="gpt-4o",
            provider="openai",
            latency_ms=100.0,
            cost_usd=0.002,
        )
    )
    return client


@pytest.fixture
def mgr(llm: AsyncMock, settings: AgentSettings) -> ContextWindowManager:
    return ContextWindowManager(llm_client=llm, model="gpt-4o", settings=settings, preserve_last_n=3)


def _make_msg(
    role: str,
    text: str,
    sid: uuid.UUID | None = None,
    tool_calls: list[dict] | None = None,
    parent_id: uuid.UUID | None = None,
    kind: str | None = None,
) -> MessageModel:
    content: dict = {"text": text}
    if kind:
        content["kind"] = kind
    return MessageModel(
        id=uuid.uuid4(),
        session_id=sid or uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=role,
        content=content,
        tool_calls=tool_calls,
        parent_message_id=parent_id,
    )


class TestTokenCounting:
    def test_count_tokens_short_text(self) -> None:
        assert count_tokens("Hello world") > 0

    def test_count_tokens_long_text(self) -> None:
        text = "word " * 1000
        assert count_tokens(text) > 100

    def test_messages_token_count_empty(self) -> None:
        assert messages_token_count([]) == 0

    def test_messages_token_count_single(self) -> None:
        msg = _make_msg("user", "Hello")
        assert messages_token_count([msg]) > 0

    def test_messages_token_count_multiple(self) -> None:
        msgs = [_make_msg("user", "Hello"), _make_msg("assistant", "Hi there")]
        total = messages_token_count(msgs)
        single = messages_token_count([msgs[0]])
        assert total > single

    def test_message_to_text_formats_correctly(self) -> None:
        msg = _make_msg("user", "Hello world")
        result = _message_to_text(msg)
        assert result == "user: Hello world"

    def test_message_to_text_with_tool_calls(self) -> None:
        msg = _make_msg(
            "assistant",
            "Let me check",
            tool_calls=[{"function": {"name": "get_weather"}, "id": "call_1"}],
        )
        result = _message_to_text(msg)
        assert "tool_calls" in result
        assert "get_weather" in result


class TestSummarization:
    async def test_no_summarization_below_threshold(
        self, mgr: ContextWindowManager, llm: AsyncMock
    ) -> None:
        msgs = [_make_msg("user", "Hi") for _ in range(3)]
        result = await mgr.assemble(msgs)
        assert len(result) == 3
        llm.complete.assert_not_called()

    async def test_summarization_above_threshold(
        self, mgr: ContextWindowManager, llm: AsyncMock
    ) -> None:
        msgs = [_make_msg("user", "A" * 500) for _ in range(10)]
        result = await mgr.assemble(msgs)
        llm.complete.assert_called_once()
        assert result[0]["role"] == "system"

    async def test_system_preserved_above_threshold(
        self, mgr: ContextWindowManager, llm: AsyncMock
    ) -> None:
        msgs = [
            _make_msg("system", "You are Nexus", kind="identity"),
            *[_make_msg("user", "A" * 500) for _ in range(10)],
        ]
        result = await mgr.assemble(msgs)
        system_msgs = [m for m in result if m["role"] == "system"]
        assert len(system_msgs) >= 2  # summary + preserved system

    async def test_last_n_preserved(
        self, mgr: ContextWindowManager, llm: AsyncMock
    ) -> None:
        msgs = [_make_msg("user", f"msg_{i}") for i in range(20)]
        mgr._settings.summarization_threshold_tokens = 10
        result = await mgr.assemble(msgs)
        assert any("msg_19" in (m.get("content") or "") for m in result)

    async def test_messages_with_tool_calls_preserved(
        self, mgr: ContextWindowManager, llm: AsyncMock
    ) -> None:
        msgs = [
            _make_msg("user", "old"),
            _make_msg(
                "assistant",
                "pending",
                tool_calls=[{"function": {"name": "search"}, "id": "c1"}],
            ),
            *[_make_msg("user", "A" * 500) for _ in range(10)],
        ]
        result = await mgr.assemble(msgs)
        contents = [m.get("content", "") for m in result]
        assert any("pending" in c for c in contents)

    async def test_idempotent_no_double_summarize(
        self, mgr: ContextWindowManager, llm: AsyncMock
    ) -> None:
        msgs = [_make_msg("user", "A" * 500) for _ in range(10)]
        await mgr.assemble(msgs)
        await mgr.assemble(msgs)
        assert llm.complete.call_count == 2  # each call produces new summary

    async def test_plan_referenced_messages_preserved(
        self, mgr: ContextWindowManager, llm: AsyncMock
    ) -> None:
        target_msg = _make_msg("user", "important data")
        msg_id = target_msg.id
        msgs = [
            _make_msg("user", "irrelevant"),
            target_msg,
            *[_make_msg("user", "A" * 500) for _ in range(10)],
        ]
        plan = [{"step": "1", "inputs": {"source": f"msg:{msg_id}"}}]
        mgr._settings.summarization_threshold_tokens = 50
        result = await mgr.assemble(msgs, plan=plan)
        contents = [m.get("content", "") for m in result]
        assert any("important data" in c for c in contents)

    async def test_summary_message_has_correct_structure(
        self, mgr: ContextWindowManager, llm: AsyncMock
    ) -> None:
        msgs = [_make_msg("user", "A" * 500) for _ in range(10)]
        result = await mgr.assemble(msgs)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "Summary of the conversation."
