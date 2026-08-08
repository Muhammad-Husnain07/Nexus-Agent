"""Tests for the deterministic PlanValidatorNode (Phase 3)."""

from __future__ import annotations

import asyncio

from nexus.agent.nodes.plan_validator_node import (
    PlanValidatorNode,
    ViolationAction,
    _find_cycle,
    _missing_inputs,
)


def _node(op: str, inputs: dict | None = None, depends_on: list[str] | None = None) -> dict:
    return {
        "op": op,
        "ref": f"Step-{op}",
        "inputs": inputs or {},
        "depends_on": depends_on or [],
    }


def _inject_gc(monkeypatch, capability_index=None, providers=None) -> None:
    _caps = capability_index if capability_index is not None else {}
    _provs = providers if providers is not None else {}

    class _GC:
        capability_index = _caps
        capability_providers = _provs

    monkeypatch.setattr(
        "nexus.agent.nodes.plan_validator_node._gc_mod.get_global_context", lambda: _GC()
    )


def test_empty_plan_valid():
    report = PlanValidatorNode().validate([])
    assert report.valid is True


def test_undefined_op_dropped(monkeypatch):
    _inject_gc(monkeypatch, capability_index={"known_op": {}})
    report = PlanValidatorNode().validate([_node("no_such_capability")])
    assert report.valid is False
    assert any(v.code == "undefined_op" for v in report.violations)
    assert report.action == ViolationAction.DROP_OP


def test_cycle_detected():
    nodes = [
        _node("a", depends_on=["b"]),
        _node("b", depends_on=["c"]),
        _node("c", depends_on=["a"]),
    ]
    cycle = _find_cycle(nodes)
    assert len(cycle) >= 2
    report = PlanValidatorNode().validate(nodes)
    assert any(v.code == "cycle" for v in report.violations)
    assert report.valid is False


def test_acyclic_chain_no_cycle():
    nodes = [
        _node("a", depends_on=[]),
        _node("b", depends_on=["a"]),
        _node("c", depends_on=["b"]),
    ]
    assert _find_cycle(nodes) == []


def test_missing_inputs_from_schema(monkeypatch):
    """Required inputs from the tool schema that the plan lacks."""
    class _Meta:
        def get(self, key, default=None):
            if key == "input_required":
                return ["latitude", "longitude"]
            return default

    class _GC:
        capability_index = {"get_current_weather": _Meta()}
        capability_providers = {}

    monkeypatch.setattr(
        "nexus.agent.nodes.plan_validator_node._gc_mod.get_global_context", lambda: _GC()
    )
    missing = _missing_inputs("get_current_weather", {"latitude"})
    assert missing == {"longitude"}


def test_no_schema_no_guess():
    """Capabilities without declared required inputs report nothing."""
    assert _missing_inputs("mystery_op", {"x"}) == set()


def test_budget_violation(monkeypatch):
    class _GC:
        capability_index = {}
        capability_providers = {
            "expensive_op": [{"cost_per_call": 0.30}],
            "cheap_op": [{"cost_per_call": 0.05}],
        }

    monkeypatch.setattr(
        "nexus.agent.nodes.plan_validator_node._gc_mod.get_global_context", lambda: _GC()
    )
    report = PlanValidatorNode(budget_cap_usd=0.20).validate(
        [_node("expensive_op"), _node("cheap_op")]
    )
    assert any(v.code == "budget" for v in report.violations)
    assert report.valid is False


def test_budget_within_cap(monkeypatch):
    class _GC:
        capability_index = {}
        capability_providers = {"cheap_op": [{"cost_per_call": 0.05}]}

    monkeypatch.setattr(
        "nexus.agent.nodes.plan_validator_node._gc_mod.get_global_context", lambda: _GC()
    )
    report = PlanValidatorNode(budget_cap_usd=0.20).validate([_node("cheap_op")])
    assert report.valid is True


def test_approval_warning_not_blocking(monkeypatch):
    class _Meta:
        def get(self, key, default=None):
            if key == "requires_approval":
                return True
            if key == "risk_level":
                return "high"
            return default

    class _GC:
        capability_index = {"risky_op": _Meta()}
        capability_providers = {}

    monkeypatch.setattr(
        "nexus.agent.nodes.plan_validator_node._gc_mod.get_global_context", lambda: _GC()
    )
    report = PlanValidatorNode().validate([_node("risky_op")])
    assert any(v.code == "approval_required" for v in report.violations)
    assert report.valid is True  # approval is informational; gate enforces


def test_rounds_abort(monkeypatch):
    """After max rounds the validator aborts with explicit errors."""
    _inject_gc(monkeypatch, capability_index={"known_op": {}})
    node = PlanValidatorNode()
    state: dict = {"_logical_workflow": {"nodes": [_node("no_such_capability")]}, "_plan_validator_rounds": 5}
    out = asyncio.run(node(state))
    assert out["_plan_validator_action"] == "abort"
    assert out["errors"]

    state2: dict = {"_logical_workflow": {"nodes": [_node("no_such_capability")]}, "_plan_validator_rounds": 0}
    out2 = asyncio.run(node(state2))
    assert out2["_plan_validator_action"] == "refine"
    assert out2["_plan_validator_rounds"] == 1


# ---------------------------------------------------------------------------
# P4 — Intent coverage, traceability, and empty-plan policy
# ---------------------------------------------------------------------------


def _inject_keyword_gc(monkeypatch, keywords, input_required=None):
    """Fake GlobalContext mirroring the real shape: capability_index keyed
    by capability NAME; capability_keywords for the O(1) keyword map."""
    cap_names = sorted({c for caps, _p, _c in keywords.values() for c in caps})
    keyword_map = {
        kw: [c for c in caps if c in cap_names]
        for kw, (caps, _p, _c) in keywords.items()
    }
    required_map = input_required or {}

    class _GC:
        capability_index = {
            name: {
                "produces": [],
                "consumes": [],
                "input_required": required_map.get(name, []),
            }
            for name in cap_names
        }
        capability_keywords = keyword_map
        capability_providers = {}

        def match_capabilities(self, tokens):
            matched = set()
            for kw, caps in keyword_map.items():
                if kw in tokens:
                    matched.update(caps)
            return list(matched)

    monkeypatch.setattr(
        "nexus.agent.nodes.plan_validator_node._gc_mod.get_global_context",
        lambda: _GC(),
    )
    monkeypatch.setattr(
        "nexus.context.global_context.get_global_context",
        lambda: _GC(),
    )


KEYWORDS = {
    "weather": (["get_current_weather"], ["latitude", "longitude"], ["temperature"]),
    "temperature": (["get_current_weather"], [], []),
    "exchange": (["get_exchange_rates"], [], []),
    "rate": (["get_exchange_rates"], [], []),
    "country": (["get_country_info"], [], []),
    "population": (["get_country_info"], [], []),
    "post": (["jsonplaceholder_request"], [], []),
    "fetch": (["jsonplaceholder_request"], [], []),
    "books": (["search_books"], [], []),
    "define": (["define_word"], [], []),
    "manga": (["search_manga"], [], []),
    "author": (["search_authors"], [], []),
}


def test_intent_coverage_missing_subintents(monkeypatch):
    """T2-class: multiple detected units, one planned op → coverage violation."""
    _inject_keyword_gc(monkeypatch, KEYWORDS)
    report = PlanValidatorNode().validate(
        [_node("get_country_info")],
        user_query=(
            "Compare the temperature in Tokyo and Osaka, "
            "then get the country info for Japan"
        ),
    )
    assert any(v.code == "intent_coverage" for v in report.violations)
    assert report.metrics["intent_coverage"] < 1.0
    assert report.metrics["dropped_intents"] >= 1
    assert report.action == ViolationAction.REFINE


def test_intent_traceability_extraneous_operation(monkeypatch):
    """T5-class: an invented op traceable to no intent unit → extraneous."""
    _inject_keyword_gc(monkeypatch, KEYWORDS)
    report = PlanValidatorNode().validate(
        [_node("get_country_info"), _node("reverse_geocode")],
        user_query="What's the population of France?",
    )
    assert any(v.code == "extraneous_operation" for v in report.violations)
    assert "reverse_geocode" in report.metrics["extraneous_operations"]


def test_intent_coverage_wrong_op_anchoring(monkeypatch):
    """T1-class: 3 nodes all mapped to one capability — coverage counts
    units, not ops."""
    _inject_keyword_gc(monkeypatch, KEYWORDS)
    report = PlanValidatorNode().validate(
        [
            _node("get_current_weather", {"latitude": 1, "longitude": 2}),
            _node("get_current_weather", {"latitude": 3, "longitude": 4}),
            _node("get_current_weather", {"latitude": 5, "longitude": 6}),
        ],
        user_query=(
            "What's the weather in Lahore, the exchange rate from USD to PKR, "
            "and tell me about Pakistan?"
        ),
    )
    assert any(v.code == "intent_coverage" for v in report.violations)
    assert report.metrics["intent_coverage"] < 1.0


def test_empty_plan_policy_executable_query(monkeypatch):
    """P4-2: an executable query with an empty plan must NOT pass as valid."""
    _inject_keyword_gc(monkeypatch, KEYWORDS)
    report = PlanValidatorNode().validate(
        [],
        user_query="Fetch post 3 from jsonplaceholder",
    )
    assert report.valid is False
    assert any(v.code == "empty_plan" for v in report.violations)
    assert report.metrics.get("empty_plan") is True


def test_empty_plan_still_valid_for_conversational(monkeypatch):
    """A pure conversational query keeps the valid empty plan."""
    _inject_keyword_gc(monkeypatch, KEYWORDS)
    report = PlanValidatorNode().validate(
        [],
        user_query="Hi, how are you?",
    )
    assert report.valid is True


def test_full_coverage_passes(monkeypatch):
    """A plan serving every detected unit passes the coverage check."""
    _inject_keyword_gc(monkeypatch, KEYWORDS)
    report = PlanValidatorNode().validate(
        [
            _node("get_current_weather", {"latitude": 1, "longitude": 2}),
            _node("get_exchange_rates"),
            _node("get_country_info"),
        ],
        user_query=(
            "What's the weather in Lahore, the exchange rate from USD to PKR, "
            "and tell me about Pakistan?"
        ),
    )
    assert not any(v.code == "intent_coverage" for v in report.violations)
    assert report.metrics["intent_coverage"] == 1.0


def test_parameter_provenance_guessed_values(monkeypatch):
    """P0: 'correct op + wrong parameter' — hardcoded coordinates for a city
    the user named must be flagged (no provenance), not executed."""
    _inject_keyword_gc(monkeypatch, KEYWORDS, {
        "get_current_weather": ["latitude", "longitude"],
    })
    report = PlanValidatorNode().validate(
        [
            _node("get_current_weather", {
                "latitude": 35.6895, "longitude": 139.6917,
            }),
        ],
        user_query="Weather in Islamabad",
    )
    assert any(v.code == "parameter_provenance" for v in report.violations)


def test_parameter_provenance_user_values_pass(monkeypatch):
    """Values traceable to the user request are legitimate."""
    _inject_keyword_gc(monkeypatch, KEYWORDS, {
        "get_current_weather": ["latitude", "longitude"],
    })
    report = PlanValidatorNode().validate(
        [
            _node("get_current_weather", {
                "latitude": "${StepG.result.latitude}",
                "longitude": "${StepG.result.longitude}",
            }),
        ],
        user_query="Weather in Tokyo",
    )
    assert not any(v.code == "parameter_provenance" for v in report.violations)


def test_parameter_provenance_numeric_canonical(monkeypatch):
    """Canonical numeric matching: 34.0 matches '34 degrees'."""
    from nexus.agent.nodes.plan_validator_node import _value_in_message

    assert _value_in_message(34.0, "what is 34 degrees in fahrenheit")
    assert _value_in_message(7, "fetch post 7")
    assert _value_in_message(35.6895, "Weather in Islamabad") is False
