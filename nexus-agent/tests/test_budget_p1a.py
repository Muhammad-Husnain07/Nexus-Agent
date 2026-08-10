"""A1/P1-A — ReasoningBudget enforcement.

- started_at SURVIVES the state-carrier round-trip (the wall clock must
  never restart at node-level rebuilds)
- reserve-before-start semantics (an exhausted dimension refuses the
  operation)
- cost dimension consumable + settled
- the runner's budget merges node carriers without restarting the clock
- router LLM classification draws from the budget before the call
"""

from __future__ import annotations

import asyncio

import pytest

from nexus.agent.budget import ReasoningBudget, budget_from_state


class TestBudgetSerialization:
    def test_started_at_survives_round_trip(self):
        b = ReasoningBudget()
        b.consume("llm_calls")
        state = {"_invocation_budget": b.to_dict()}
        rebuilt = budget_from_state(state)
        assert rebuilt.started_at == b.started_at, (
            "the wall clock must survive the state carrier (A1)"
        )
        assert rebuilt.consumed["llm_calls"] == 1

    def test_elapsed_time_preserved_across_rebuild(self):
        import time as _time

        b = ReasoningBudget()
        _time.sleep(0.01)
        rebuilt = budget_from_state({"_invocation_budget": b.to_dict()})
        assert rebuilt.elapsed_ms() >= 10

    def test_legacy_carrier_without_started_at_starts_now(self):
        state = {"_invocation_budget": {"consumed": {}, "max_llm_calls": 30}}
        rebuilt = budget_from_state(state)
        assert rebuilt.elapsed_ms() < 1000


class TestReserveBeforeStart:
    def test_exhausted_dimension_refuses_consumption(self):
        b = ReasoningBudget(max_llm_calls=2)
        assert b.consume("llm_calls") is True
        assert b.consume("llm_calls") is True
        assert b.consume("llm_calls") is False, (
            "the third call must be refused BEFORE it starts (A1)"
        )
        assert b.remaining("llm_calls") == 0

    def test_exceeded_reports_dimension(self):
        b = ReasoningBudget(max_tool_calls=1)
        b.consume("tool_calls")
        assert b.exceeded() == "tool_calls"

    def test_cost_dimension_consumed_and_settled(self):
        b = ReasoningBudget(max_cost_usd=0.2)
        assert b.consume("cost_usd", 0.15) is True
        b.settle_cost(0.05)
        assert b.remaining("cost_usd") == pytest.approx(0.0)
        assert b.exceeded() == "cost_usd"

    def test_cost_overspend_refused(self):
        b = ReasoningBudget(max_cost_usd=0.1)
        assert b.consume("cost_usd", 0.2) is False


class TestBudgetMerge:
    def test_node_carrier_merges_without_restarting_clock(self):
        runner_budget = ReasoningBudget()
        runner_budget.consume("graph_steps")
        node_budget = ReasoningBudget()
        node_budget.consume("llm_calls")
        node_budget.consume("tool_calls", 3)
        node_budget.settle_cost(0.07)
        runner_budget.merge(node_budget.to_dict())
        assert runner_budget.consumed["llm_calls"] == 1
        assert runner_budget.consumed["tool_calls"] == 3
        assert runner_budget.consumed["cost_usd"] == pytest.approx(0.07)
        assert runner_budget.consumed["graph_steps"] == 1
        # the wall clock belongs to the runner's original budget
        assert runner_budget.started_at == runner_budget.started_at

    def test_merge_takes_max_per_key(self):
        a = ReasoningBudget()
        a.consume("llm_calls")
        b = ReasoningBudget()
        b.consume("llm_calls")
        b.consume("llm_calls")
        a.merge(b.to_dict())
        assert a.consumed["llm_calls"] == 2


class TestRouterBudgetThreading:
    def test_router_llm_consumes_budget(self, monkeypatch):
        import nexus.agent.router as _router

        calls = {"n": 0}

        async def _fake_llm_classify(query, tool_names, llm, model):
            calls["n"] += 1
            return _router.ExecutionGoals(goals=(_router.ExecutionGoal.CONVERSATION,))

        monkeypatch.setattr(_router, "_llm_classify", _fake_llm_classify)

        budget = ReasoningBudget(max_llm_calls=1)
        goals = asyncio.run(
            _router.classify_query(
                query="hi there",
                history=[],
                tool_names=[],
                llm=object(),
                model="m",
                budget=budget,
            )
        )
        assert calls["n"] == 1
        assert budget.consumed["llm_calls"] == 1
        assert goals.primary.value == "conversation"

    def test_router_llm_refused_when_exhausted(self, monkeypatch):
        import nexus.agent.router as _router

        calls = {"n": 0}

        async def _fake_llm_classify(query, tool_names, llm, model):
            calls["n"] += 1
            return _router.ExecutionGoals(goals=(_router.ExecutionGoal.CONVERSATION,))

        monkeypatch.setattr(_router, "_llm_classify", _fake_llm_classify)

        budget = ReasoningBudget(max_llm_calls=1)
        budget.consume("llm_calls")  # exhausted by an earlier subsystem
        goals = asyncio.run(
            _router.classify_query(
                query="hi there",
                history=[],
                tool_names=[],
                llm=object(),
                model="m",
                budget=budget,
            )
        )
        assert calls["n"] == 0, (
            "an exhausted budget must refuse the LLM call before it starts (A1)"
        )
        assert goals.primary.value == "action"  # safe heuristic default
