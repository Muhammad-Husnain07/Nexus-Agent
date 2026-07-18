"""Unit tests for EpisodicSummarizer with mocked LLM."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.llm.client import LLMResponse, UsageInfo
from nexus.memory.summarizer import EpisodicSummarizer


class TestEpisodicSummarizer:
    """EpisodicSummarizer — compress agent run into 3-5 sentence summary."""

    @pytest.fixture
    def llm(self) -> MagicMock:
        client = MagicMock()
        client.complete = AsyncMock(
            return_value=LLMResponse(
                content="User asked to send an email. The send_email tool was called successfully. No errors.",
                usage=UsageInfo(prompt_tokens=50, completion_tokens=20, total_tokens=70),
                model="gpt-4o",
                provider="openai",
                latency_ms=100,
                cost_usd=0.001,
            ),
        )
        return client

    @pytest.fixture
    def summarizer(self, llm: MagicMock) -> EpisodicSummarizer:
        return EpisodicSummarizer(llm=llm, model="gpt-4o")

    async def test_summarize_returns_string(self, summarizer: EpisodicSummarizer) -> None:
        agent_state = {
            "messages": [{"role": "user", "content": "send an email"}],
            "tool_results": [{"tool_name": "send_email", "status": "success"}],
            "plan": [{"description": "Send email", "tool_name": "send_email"}],
            "errors": [],
            "intent": {"intent": "send email"},
        }

        summary = await summarizer.summarize(agent_state)
        assert isinstance(summary, str)
        assert len(summary) > 0

    async def test_summarize_empty_state(self, summarizer: EpisodicSummarizer) -> None:
        summary = await summarizer.summarize({})
        assert isinstance(summary, str)

    async def test_build_transcript(self) -> None:
        transcript = EpisodicSummarizer._build_transcript({
            "messages": [{"role": "user", "content": "hello"}],
            "tool_results": [{"tool_name": "test", "status": "success"}],
            "plan": [{"description": "Step 1", "tool_name": "test"}],
            "errors": ["error1"],
            "intent": {"intent": "greet"},
        })
        assert "User message: hello" in transcript
        assert "Last tool result: test" in transcript
        assert "error1" in transcript
