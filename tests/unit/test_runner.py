"""Tests for AgentRunner — lock enforcement, event translation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.agent.runner import AgentRunner


class TestAgentRunnerBasics:
    """Verify AgentRunner builds fresh graphs and enforces locks."""

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

    async def test_invoke_yields_events(self, runner: AgentRunner) -> None:
        mock_event = MagicMock()
        mock_event.__iter__ = lambda s: iter([{"understand_intent": {"intent": {"intent": "test"}}}])

        with (
            patch.object(runner, "_build_graph") as mock_build,
            patch("nexus.agent.runner.get_redis_client", return_value=None),
        ):
            mock_graph = MagicMock()
            mock_graph.astream = lambda *a, **kw: mock_event.__iter__()
            mock_build.return_value = mock_graph

            events = []
            async for e in runner.invoke(
                session_id="s1",
                user_message="test",
                tenant_id="t1",
                user_id="u1",
            ):
                events.append(e)
            assert len(events) >= 1
            # Verify a fresh graph was built
            mock_build.assert_called_once()

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

    async def test_resume_yields_events(self, runner: AgentRunner) -> None:
        """Verify resume() builds fresh graph and streams events."""
        async def _mock_astream(*args: object, **kwargs: object):
            yield {"finalize": {"final_response": "Resumed."}}

        with (
            patch.object(runner, "_build_graph") as mock_build,
            patch("nexus.agent.runner.get_redis_client", return_value=None),
        ):
            mock_graph = MagicMock()
            mock_graph.aget_state = AsyncMock(return_value=MagicMock(next=["execute_step"]))
            mock_graph.astream = _mock_astream
            mock_build.return_value = mock_graph

            events = []
            async for e in runner.resume("s1", {"action": "approve"}):
                events.append(e)
            assert len(events) >= 1
            has_final = any(e.type == "final_response" for e in events)
            assert has_final

    async def test_resume_no_paused_run(self, runner: AgentRunner) -> None:
        """Verify resume() yields error when no paused run exists."""
        with (
            patch.object(runner, "_build_graph") as mock_build,
            patch("nexus.agent.runner.get_redis_client", return_value=None),
        ):
            mock_graph = MagicMock()
            mock_graph.aget_state = AsyncMock(return_value=MagicMock(next=[]))
            mock_build.return_value = mock_graph

            events = []
            async for e in runner.resume("s1", {"action": "approve"}):
                events.append(e)
            assert len(events) == 1
            assert events[0].type == "error"
            assert "No paused run" in events[0].payload.get("message", "")


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
