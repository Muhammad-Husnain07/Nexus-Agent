"""ReasoningBudget tests (P0) — the per-invocation reasoning contract.

Reserve-before-execute semantics: consuming beyond a limit returns False;
the exceeded() check reports the first exhausted dimension; the shared
replan counter unifies the validator/compiler/recovery loops.
"""

from __future__ import annotations

from nexus.agent.budget import ReasoningBudget


def test_consume_reserve_before_execute():
    b = ReasoningBudget(max_replans=2)
    assert b.consume("replans") is True
    assert b.consume("replans") is True
    assert b.consume("replans") is False  # the third replan is refused
    assert b.exceeded() == "replans"


def test_remaining():
    b = ReasoningBudget(max_tool_calls=3)
    assert b.remaining("tool_calls") == 3
    b.consume("tool_calls", 2)
    assert b.remaining("tool_calls") == 1


def test_wall_time_exceeded(monkeypatch):
    import nexus.agent.budget as budget_mod

    real_time = budget_mod.time.perf_counter
    t = [0.0]

    def fake_now() -> float:
        return t[0]

    monkeypatch.setattr(budget_mod.time, "perf_counter", fake_now)
    b = ReasoningBudget(max_wall_time_ms=1000, started_at=0.0)
    t[0] = 2.0  # 2s elapsed > 1s limit
    assert b.exceeded() == "wall_time"
    monkeypatch.setattr(budget_mod.time, "perf_counter", real_time)


def test_to_dict_round_trip():
    b = ReasoningBudget(max_replans=1)
    b.consume("replans")
    d = b.to_dict()
    assert d["consumed"]["replans"] == 1
    rebuilt = ReasoningBudget(
        max_replans=d["max_replans"],
        consumed=dict(d["consumed"]),
    )
    assert rebuilt.remaining("replans") == 0


def test_budget_from_state():
    from nexus.agent.budget import budget_from_state

    b = budget_from_state({
        "_invocation_budget": {
            "max_replans": 3,
            "consumed": {"replans": 1},
            "_started_at": 0.0,
        },
    })
    assert b.max_replans == 3
    assert b.remaining("replans") == 2
