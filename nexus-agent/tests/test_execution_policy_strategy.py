"""Tests for ExecutionPolicy + ExecutionStrategy (Phase 4)."""

from __future__ import annotations

from nexus.execution.policy import ExecutionPolicy, policy_from_contract
from nexus.execution.strategy import ExecutionStrategy, select_strategy


def _node(op: str, iterate_over: str | None = None, kind: str = "tool") -> dict:
    n = {"op": op, "kind": kind}
    if iterate_over:
        n["iterate_over"] = iterate_over
    return n


def test_policy_from_unified_block():
    contract = {
        "execution_policy": {
            "timeout_s": 5.0,
            "retries": 2,
            "idempotent": True,
            "risk_level": "high",
            "requires_approval": True,
            "cacheable": False,
            "permissions": ["billing"],
            "rollback": "refund_order",
            "maintenance_windows": ["2026-01-01T00:00:00Z"],
        }
    }
    policy = policy_from_contract(contract)
    assert policy.timeout_s == 5.0
    assert policy.retries == 2
    assert policy.idempotent is True
    assert policy.risk_level == "high"
    assert policy.requires_approval is True
    assert policy.cacheable is False
    assert policy.permissions == ("billing",)
    assert policy.rollback == "refund_order"
    assert policy.maintenance_windows == ("2026-01-01T00:00:00Z",)


def test_policy_legacy_fallback():
    """Old contract keys remain readable — readers never break."""
    policy = policy_from_contract({
        "idempotent": True,
        "risk_level": "medium",
        "requires_approval": False,
        "cacheable": False,
        "compensating_operation": "undo_it",
    })
    assert policy.idempotent is True
    assert policy.risk_level == "medium"
    assert policy.cacheable is False
    assert policy.rollback == "undo_it"
    assert policy.timeout_s == 20.0  # safe default, never guessed


def test_policy_defaults_on_garbage():
    policy = policy_from_contract(None)
    assert policy.risk_level == "low"
    assert policy.requires_approval is False
    assert policy.permissions == ()


def test_policy_frozen():
    policy = policy_from_contract({})
    try:
        policy.timeout_s = 99.0  # type: ignore[misc]
        raise AssertionError("should be frozen")
    except Exception:
        pass


def test_strategy_map_when_iterate_over():
    d = select_strategy([_node("a", iterate_over="items")], waves=[["a"]])
    assert d.strategy == ExecutionStrategy.MAP


def test_strategy_reduce_with_aggregate():
    d = select_strategy(
        [_node("a", iterate_over="items"), _node("b", kind="aggregate")],
        waves=[["a"], ["b"]],
    )
    assert d.strategy == ExecutionStrategy.REDUCE


def test_strategy_sequential_multiple_waves():
    d = select_strategy([_node("a"), _node("b")], waves=[["a"], ["b"]])
    assert d.strategy == ExecutionStrategy.SEQUENTIAL


def test_strategy_parallel_single_wave():
    d = select_strategy([_node("a"), _node("b"), _node("c")], waves=[["a", "b", "c"]])
    assert d.strategy == ExecutionStrategy.PARALLEL


def test_strategy_single_step_sequential():
    d = select_strategy([_node("a")], waves=[["a"]])
    assert d.strategy == ExecutionStrategy.SEQUENTIAL


def test_strategy_background_by_latency_threshold():
    d = select_strategy(
        [_node("a")],
        waves=[["a"]],
        estimated_latency_ms=30000,
        background_threshold_ms=15000,
    )
    assert d.background is True
    d2 = select_strategy(
        [_node("a")],
        waves=[["a"]],
        estimated_latency_ms=300,
        background_threshold_ms=15000,
    )
    assert d2.background is False


def test_strategy_no_background_without_threshold():
    d = select_strategy([_node("a")], waves=[["a"]], estimated_latency_ms=99999)
    assert d.background is False
