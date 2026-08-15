"""D2/P0-D — terminal checkpoint recovery (I6).

A terminal-abnormal invocation checkpoint must never silently continue the
old graph: the next invocation starts fresh planning/execution, and the
state endpoint reports the truthful terminal status.
"""

from __future__ import annotations

from nexus.agent.runner import _TERMINAL_ABNORMAL, _terminal_reset_needed
from nexus.api.chat import derive_run_status


class TestTerminalResetDecision:
    def test_terminal_abnormal_statuses_require_reset(self):
        for status in ("CANCELLED", "TIMED_OUT", "INTERRUPTED", "FAILED"):
            assert _terminal_reset_needed(status) is True, status

    def test_non_terminal_statuses_do_not_reset(self):
        for status in (None, "", "RUNNING", "COMPLETED"):
            assert _terminal_reset_needed(status) is False, str(status)

    def test_terminal_set_complete(self):
        assert frozenset(
            {"CANCELLED", "TIMED_OUT", "INTERRUPTED", "FAILED"}
        ) == _TERMINAL_ABNORMAL


class TestRunStatusMapping:
    def test_terminal_abnormal_reported_truthfully(self):
        assert derive_run_status(True, "TIMED_OUT") == "timed_out"
        assert derive_run_status(True, "INTERRUPTED") == "interrupted"
        assert derive_run_status(True, "CANCELLED") == "cancelled"
        assert derive_run_status(True, "FAILED") == "failed"

    def test_completed_marker_maps_to_completed(self):
        assert derive_run_status(True, "COMPLETED") == "completed"
        assert derive_run_status(False, None) == "completed"

    def test_active_run_reports_running(self):
        assert derive_run_status(True, "RUNNING") == "running"
        assert derive_run_status(True, None) == "running"


class _FakeGraph:
    """Minimal LangGraph stand-in: records aupdate_state patches."""

    def __init__(self) -> None:
        self.updates: list[tuple[dict, str | None]] = []

    async def aget_state(self, config):  # type: ignore[no-untyped-def]
        class _State:
            values: dict = {}

        return _State()

    async def astream(self, initial_state, run_config, stream_mode="updates"):  # type: ignore[no-untyped-def]
        yield {"FakeNode": {"messages": [{"role": "assistant", "content": "hi"}]}}

    async def aupdate_state(self, run_config, patch, as_node=None):  # type: ignore[no-untyped-def]
        self.updates.append((dict(patch), as_node))


class _BudgetExceededImmediately:
    """ReasoningBudget stand-in: exceeded on the first check."""

    def __init__(self, **kwargs) -> None:  # noqa: ARG002
        self.consumed: dict[str, int] = {}

    def merge(self, carrier):  # type: ignore[no-untyped-def]
        return None

    def consume(self, dimension: str) -> bool:  # noqa: ARG002
        self.consumed[dimension] = self.consumed.get(dimension, 0) + 1
        return True

    def exceeded(self) -> str | None:
        return "wall_time"

    def to_dict(self) -> dict:
        return {"max_wall_time_ms": 1}


class _BudgetNeverExceeded(_BudgetExceededImmediately):
    def exceeded(self) -> str | None:
        return None


class TestRunnerTerminalFinalization:
    """PH-1 (I16): a budget-exceeded invocation must persist TIMED_OUT, never
    COMPLETED — the terminal marker is monotonic and reaches the checkpoint."""

    async def _run(self, monkeypatch, budget_cls) -> tuple[list, _FakeGraph]:
        import nexus.agent.budget as _budget_mod
        import nexus.agent.runner as _runner_mod
        from nexus.agent.runner import AgentRunner

        graph = _FakeGraph()
        monkeypatch.setattr(_runner_mod, "get_redis_client", lambda: None)
        monkeypatch.setattr(
            _runner_mod, "persist_outcome", _noop_persist
        )
        monkeypatch.setattr(_budget_mod, "ReasoningBudget", budget_cls)

        runner = AgentRunner()
        monkeypatch.setattr(runner, "_build_graph", _make_build_graph(graph))

        events: list = []
        async for ev in runner.invoke(
            session_id="11111111-2222-3333-4444-555555555555", user_message="hi"
        ):
            events.append(ev)
        return events, graph

    async def test_budget_exceeded_persists_timed_out_never_completed(
        self, monkeypatch
    ):
        events, graph = await self._run(monkeypatch, _BudgetExceededImmediately)

        # The user-visible error event fires.
        assert any(getattr(ev, "type", None) == "error" for ev in events)
        # Every persisted update carries the terminal marker — and it is
        # NEVER downgraded to COMPLETED after the marker was set.
        assert graph.updates, "expected checkpoint writes"
        for patch, _as_node in graph.updates:
            assert patch.get("_invocation_status") == "TIMED_OUT", patch
        # The finally block resets the pending graph (I6) so the stale
        # plan cannot silently continue on the next invocation.
        assert any(as_node == "__start__" for _p, as_node in graph.updates)
        # The state endpoint would report the truthful terminal status.
        assert derive_run_status(True, "TIMED_OUT") == "timed_out"

    async def test_normal_completion_still_persists_completed(self, monkeypatch):
        events, graph = await self._run(monkeypatch, _BudgetNeverExceeded)

        assert not any(getattr(ev, "type", None) == "error" for ev in events)
        assert graph.updates, "expected checkpoint writes"
        assert graph.updates[-1][0].get("_invocation_status") == "COMPLETED"


async def _noop_persist(outcome) -> None:  # noqa: ARG001
    return None


def _make_build_graph(graph: _FakeGraph):  # type: ignore[no-untyped-def]
    async def _build_graph() -> _FakeGraph:
        return graph

    return _build_graph
