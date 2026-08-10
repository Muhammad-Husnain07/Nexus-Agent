"""B3 ENGINE-SCORE ALIGNMENT gate (P0-B deferred, now landed).

Capability alignment is decided by the DETERMINISTIC resolver's per-unit
SCORES, never a keyword-bridge proxy or whole-query rank positions alone:

    aligned     — the plan's pick IS the engine's top candidate
    misaligned  — pick differs AND engine evidence is STRONG (unique or
                  dominant top)  → BLOCKING (ERROR/REFINE)
    ambiguous   — pick differs but scores are CLOSE → evidence only
    no_signal   — no pick or no engine candidates → existing behavior

The critical rule: ONLY STRONG evidence blocks. The historical false
positives (scenarios 8/20/38/47) all lived in weak/close-signal territory.

Adversarial cases (reviewer-specified):
1. unique high-confidence correct match  → aligned (pass)
2. unique high-confidence WRONG selection → blocking
3. close competing candidates            → ambiguous (no block)
4. no candidates                         → no_signal (existing behavior)
5. multiple valid capabilities           → no false blocking
6. pick absent from candidate set        → blocking ONLY when strong
7. negated/unclassifiable units          → excluded
8. scenario 8's get_exchange_rates       → must remain valid
"""

from __future__ import annotations

import asyncio

from nexus.agent.nodes.plan_validator_node import (
    _alignment_verdict,
)

# ---------------------------------------------------------------------------
# Pure verdict — the 8 adversarial cases
# ---------------------------------------------------------------------------


def test_case1_unique_high_confidence_correct_match_aligned():
    assert _alignment_verdict("get_valorant_agents", [("get_valorant_agents", 100.0)]) == "aligned"


def test_case2_unique_high_confidence_wrong_selection_blocks():
    assert _alignment_verdict("get_ghibli_films", [("get_valorant_agents", 100.0)]) == "misaligned"


def test_case3_close_competing_candidates_ambiguous():
    """Bitcoin-price class: engine top is weak noise (3.0) vs 3.0 — the
    correct pick is not blocked."""
    assert _alignment_verdict("bitcoin_tool", [("astronomy_pic", 3.0), ("other", 3.0)]) == "ambiguous"
    assert _alignment_verdict("other", [("astronomy_pic", 3.0), ("other", 2.9)]) == "ambiguous"


def test_case4_no_candidates_no_signal():
    assert _alignment_verdict("get_current_weather", []) == "no_signal"
    assert _alignment_verdict(None, [("get_current_weather", 100.0)]) == "no_signal"


def test_case5_multiple_valid_capabilities_no_false_block():
    """chosen == top among several → aligned (dominance irrelevant)."""
    ranked = [("get_current_weather", 5.0), ("weather_clone", 4.0), ("weather_pro", 3.0)]
    assert _alignment_verdict("get_current_weather", ranked) == "aligned"


def test_case6_absent_pick_blocks_only_when_strong():
    """A pick absent from the engine's candidate set blocks ONLY when the
    engine evidence is STRONG (dominant/unique top)."""
    # strong: unique top
    assert _alignment_verdict("get_ghibli_films", [("get_valorant_agents", 100.0)]) == "misaligned"
    # strong: dominant (7.0 >= 2 * 3.0)
    assert _alignment_verdict("other_tool", [("get_exchange_rates", 7.0), ("noise", 3.0)]) == "misaligned"
    # weak/close: absent pick must NOT block (Bitcoin/todo classes)
    assert _alignment_verdict("get_bitcoin_price", [("astronomy_pic", 3.0), ("other", 2.5)]) == "ambiguous"


def test_case7_negated_and_unclassifiable_excluded():
    """The verdict function never sees negated/unclassifiable units — the
    validator skips them before calling; verify no_signal for None pick
    (their chosen is None) and that negated handling is upstream."""
    # negated unit: no planned match → no chosen → no_signal
    assert _alignment_verdict(None, [("forbidden_op", 100.0)]) == "no_signal"


def test_case8_exchange_rates_remains_valid():
    """Scenario-8 class: get_exchange_rates IS the engine's top for the
    unit — aligned, never blocked."""
    ranked = [("get_exchange_rates", 7.0), ("noise", 3.0)]
    assert _alignment_verdict("get_exchange_rates", ranked) == "aligned"
    # even a weak top — chosen == top → aligned
    ranked_weak = [("get_exchange_rates", 2.0), ("noise", 2.0)]
    assert _alignment_verdict("get_exchange_rates", ranked_weak) == "aligned"


def test_dominance_ratio_boundary():
    """Exactly at the ratio (top == 2.0 * runner-up) is strong (blocks)."""
    assert _alignment_verdict("b", [("a", 10.0), ("b", 5.0)]) == "misaligned"
    assert _alignment_verdict("b", [("a", 10.0), ("b", 5.01)]) == "ambiguous"


def test_case9_unique_weak_top_is_ambiguous():
    """Bitcoin-price class (fixed): the engine's ONLY hit is a lone weak
    keyword-noise candidate (score 3.0) — uniqueness is NOT strength. A
    correct pick absent from that weak set must never block."""
    assert _alignment_verdict("get_bitcoin_price", [("astronomy_pic", 3.0)]) == "ambiguous"
    # a unique STRONG top still blocks
    assert _alignment_verdict("get_ghibli_films", [("get_valorant_agents", 100.0)]) == "misaligned"
    # a unique top at/above the strong floor blocks
    assert _alignment_verdict("other", [("get_exchange_rates", 7.0)]) == "misaligned"
    # a unique top exactly at the floor blocks
    assert _alignment_verdict("other", [("get_current_weather", 5.0)]) == "misaligned"


# ---------------------------------------------------------------------------
# Integration — validate() with injected engine scores
# ---------------------------------------------------------------------------


def _node(op: str) -> dict:
    return {"op": op, "inputs": {}, "depends_on": []}


def _inject_keyword_gc(monkeypatch, mapping: dict[str, list[str]]) -> None:
    """Fake GlobalContext mirroring the real shape (the established pattern
    from test_planner_p0b — keyword map + O(1) keyword index + aliases)."""
    cap_names = sorted({c for caps in mapping.values() for c in caps})
    keyword_map = {kw: [c for c in caps if c in cap_names] for kw, caps in mapping.items()}

    class _GC:
        capability_index = {
            name: {"produces": [], "consumes": [], "input_required": [], "keywords": []}
            for name in cap_names
        }
        capability_keywords = keyword_map
        capability_providers = {}
        alias_index = {}

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


from nexus.agent.nodes.plan_validator_node import PlanValidatorNode  # noqa: E402


def test_validate_aligned_plan_passes(monkeypatch):
    _inject_keyword_gc(
        monkeypatch,
        {"weather": ["get_current_weather"], "pokemon": ["get_pokemon"]},
    )
    nodes = [_node("get_current_weather"), _node("get_pokemon")]
    scores = {
        "weather in Tokyo": [("get_current_weather", 5.0), ("noise", 3.0)],
        "list pokemon": [("get_pokemon", 100.0)],
    }
    report = PlanValidatorNode().validate(
        nodes, user_query="weather in Tokyo and list pokemon", engine_scores=scores
    )
    assert report.valid is True
    assert all(v.code != "capability_alignment" for v in report.violations)
    ev = {r["unit"]: r for r in report.metrics["intent_coverage_evidence"]}
    assert ev["weather in Tokyo"]["engine_verdict"] == "aligned"
    assert ev["list pokemon"]["engine_verdict"] == "aligned"


def test_validate_strong_misalignment_blocks(monkeypatch):
    """Case 2/6 integration: the plan's pick for a unit differs from the
    engine's STRONG top → ERROR violation (blocking)."""
    _inject_keyword_gc(
        monkeypatch,
        {
            "weather": ["get_current_weather", "weather_pro"],
            "tokyo": ["get_current_weather"],
        },
    )
    nodes = [_node("weather_pro")]
    scores = {
        "weather in Tokyo": [("get_current_weather", 100.0)],  # unique, strong
    }
    report = PlanValidatorNode().validate(
        nodes, user_query="weather in Tokyo", engine_scores=scores
    )
    codes = [v.code for v in report.violations]
    assert "capability_alignment" in codes
    v = next(v for v in report.violations if v.code == "capability_alignment")
    assert v.severity.value == "error"
    ev = report.metrics["intent_coverage_evidence"][0]
    assert ev["chosen"] == "weather_pro"
    assert ev["engine_verdict"] == "misaligned"
    assert ev["aligned"] is False


def test_validate_weak_signal_never_blocks(monkeypatch):
    """Case 3/6 weak class: correct pick absent from weak engine candidates
    → ambiguous, report stays VALID (scenario-8-class protection). Uses a
    REGISTERED op (get_exchange_rates) with weak close engine scores."""
    _inject_keyword_gc(
        monkeypatch,
        {"exchange rate": ["get_exchange_rates"], "usd": ["get_exchange_rates"], "pkr": ["get_exchange_rates"]},
    )
    nodes = [_node("get_exchange_rates")]
    scores = {
        "current exchange rate of USD to PKR": [("noise_tool", 3.0), ("other_tool", 3.0)],
    }
    report = PlanValidatorNode().validate(
        nodes, user_query="current exchange rate of USD to PKR", engine_scores=scores
    )
    assert report.valid is True
    assert all(v.code != "capability_alignment" for v in report.violations)
    ev = report.metrics["intent_coverage_evidence"][0]
    assert ev["engine_verdict"] == "ambiguous"
    # ambiguous: the pick differs from the engine top (aligned=False is
    # honest) but the evidence is NOT strong — no violation, plan proceeds
    assert ev["aligned"] is False
    assert report.metrics["capability_alignment"] == 1.0


def test_validate_no_engine_scores_no_alignment_signal(monkeypatch):
    """Without engine scores the verdict is no_signal — the plan proceeds
    exactly as before (backward compatible for direct validate calls)."""
    _inject_keyword_gc(
        monkeypatch,
        {"weather": ["get_current_weather", "weather_pro"], "tokyo": ["get_current_weather"]},
    )
    report = PlanValidatorNode().validate(
        [_node("weather_pro")], user_query="weather in Tokyo"
    )
    assert report.valid is True
    ev = report.metrics["intent_coverage_evidence"][0]
    assert ev["engine_verdict"] == "no_signal"
    assert ev["aligned"] is False


def test_validate_unique_weak_top_never_blocks(monkeypatch):
    """Integration for the unique-weak fix: the engine's lone noise hit
    (3.0) must not block a correct pick absent from that set."""
    _inject_keyword_gc(
        monkeypatch,
        {"bitcoin": ["get_exchange_rates"], "exchange": ["get_exchange_rates"]},
    )
    nodes = [_node("get_exchange_rates")]
    scores = {
        "bitcoin price in USD": [("astronomy_pic", 3.0)],  # unique but weak
    }
    report = PlanValidatorNode().validate(
        nodes, user_query="bitcoin price in USD", engine_scores=scores
    )
    assert report.valid is True
    assert all(v.code != "capability_alignment" for v in report.violations)
    ev = report.metrics["intent_coverage_evidence"][0]
    assert ev["engine_verdict"] == "ambiguous"
    assert ev["engine_dominant"] is False


def test_node_path_gathers_engine_scores(monkeypatch):
    """The async node resolves per-unit engine scores and passes them into
    validate — a strong misalignment surfaces as a REFINE action."""
    _inject_keyword_gc(
        monkeypatch,
        {"weather": ["get_current_weather", "weather_pro"], "tokyo": ["get_current_weather"]},
    )

    class _Res:
        class _Cand:
            def __init__(self, name, score):
                self.name = name
                self.score = score

        def __init__(self, names):
            self.capability_candidates = [self._Cand(n, 100.0) for n in names]

    class _FakeEngine:
        calls: list[str] = []

        async def resolve(self, query, top_k=None):
            _FakeEngine.calls.append(query)
            if "weather" in query:
                return _Res(["get_current_weather"])
            return _Res([])

    import nexus.capabilities.resolution_engine as _re

    monkeypatch.setattr(_re, "get_resolution_engine", lambda: _FakeEngine())
    state = {
        "_logical_workflow": {"nodes": [_node("weather_pro")]},
        "_preferred_tools": ["get_current_weather", "weather_pro"],
        "messages": [{"role": "user", "content": "weather in Tokyo"}],
    }
    out = asyncio.run(PlanValidatorNode()(state))
    assert "weather in Tokyo" in _FakeEngine.calls
    assert out["_plan_validator_action"] in ("refine", "proceed")
    report = out["_plan_validator_report"]
    codes = [v["code"] for v in report["violations"]]
    assert "capability_alignment" in codes
    assert all(
        v["severity"] == "error"
        for v in report["violations"]
        if v["code"] == "capability_alignment"
    )
