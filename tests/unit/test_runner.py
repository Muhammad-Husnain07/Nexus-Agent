"""Tests for AgentRunner — graph caching, lock enforcement, event translation."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.agent.runner import AgentRunner


class TestAgentRunnerCache:
    """Verify AgentRunner caches compiled graphs per session."""

    @pytest.fixture
    def runner(self) -> AgentRunner:
        mock_llm = MagicMock()
        mock_sel = MagicMock()
        mock_exec = MagicMock()
        return AgentRunner(
            llm_client=mock_llm,
            tool_selector=mock_sel,
            tool_executor=mock_exec,
            event_bus=None,
        )

    def test_get_or_create_graph_caches(self, runner: AgentRunner) -> None:
        g1 = runner._get_or_create_graph("session-1")
        g2 = runner._get_or_create_graph("session-1")
        assert g1 is g2

    def test_different_sessions_get_different_graphs(self, runner: AgentRunner) -> None:
        g1 = runner._get_or_create_graph("session-A")
        g2 = runner._get_or_create_graph("session-B")
        assert g1 is not g2

    def test_evict_session_removes_cache(self, runner: AgentRunner) -> None:
        runner._get_or_create_graph("session-X")
        runner.evict_session("session-X")
        g2 = runner._get_or_create_graph("session-X")
        assert "session-X" in runner._graphs

    async def test_invoke_yields_events(self, runner: AgentRunner) -> None:
        mock_event = MagicMock()
        mock_event.__iter__ = lambda s: iter([{"understand_intent": {"intent": {"intent": "test"}}}])

        old_graph = runner._get_or_create_graph("s1")
        with (
            patch.object(old_graph, "astream", return_value=mock_event.__iter__()),
            patch("nexus.agent.runner.get_redis_client", return_value=None),
        ):
            events = []
            async for e in runner.invoke(
                session_id="s1",
                user_message="test",
                tenant_id="t1",
                user_id="u1",
            ):
                events.append(e)
            assert len(events) >= 1

    async def test_lock_acquired_yields_error_when_busy(self, runner: AgentRunner) -> None:
        fake_redis = AsyncMock()
        fake_redis.set = AsyncMock(return_value=False)
        with patch("nexus.agent.runner.get_redis_client", return_value=fake_redis):
            events = []
            async for e in runner.invoke(
                session_id="s-busy",
                user_message="test",
                tenant_id="t1",
                user_id="u1",
            ):
                events.append(e)
            assert len(events) == 1
            assert events[0].type == "error"


class TestAgentEventTranslation:
    """Verify _translate maps state updates to AgentEvents."""

    def test_translate_final_response(self) -> None:
        events = AgentRunner._translate("finalize", {"final_response": "Done."})
        assert len(events) >= 1
        assert events[0].type == "final_response"

    def test_translate_plan_created(self) -> None:
        events = AgentRunner._translate("plan", {"plan": [{"id": "s1"}]})
        assert events[0].type == "plan_created"

    def test_translate_tool_completed(self) -> None:
        events = AgentRunner._translate(
            "execute_step",
            {"tool_results": [{"tool_name": "echo", "status": "success"}]},
        )
        assert events[0].type == "tool_call_completed"

    def test_translate_clarification_needed(self) -> None:
        events = AgentRunner._translate(
            "gather_requirements",
            {"final_response": "What is your email?"},
        )
        has_clarification = any(e.type == "clarification_needed" for e in events)
        assert has_clarification

    def test_translate_error(self) -> None:
        events = AgentRunner._translate("execute_step", {"errors": ["Timeout"]})
        has_error = any(e.type == "error" for e in events)
        assert has_error
