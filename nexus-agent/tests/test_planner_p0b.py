"""P0-B planner-correctness adversarial tests (red->green on current code).

B1  IntentDetector boundary — confidence artifact fixed; syntax only.
B2  Per-intent IntentCoverage evidence (I4 GREEN).
B3  Capability alignment blocking after the repair budget is exhausted.
B4  Router backstop — deterministic executable evidence overrides a
    conversational classification.
B5  iterate_over resolvability (F1 root cause) + PlanCache key shape.

Deterministic — no live server, no LLM, no DB.
"""

from __future__ import annotations

from tests.helpers import inject_keyword_gc

import asyncio
import json

from nexus.agent.nodes.plan_validator_node import PlanValidatorNode
from nexus.agent.planners.intent_detector import IntentDetector


def _node(op: str, **extra) -> dict:
    n = {"op": op, "inputs": {}, "depends_on": []}
    n.update(extra)
    return n





# ---------------------------------------------------------------------------
# B1 — IntentDetector boundary (syntax only; confidence artifact fixed)
# ---------------------------------------------------------------------------


class TestB1DetectorConfidence:
    def test_single_short_clause_is_not_full_confidence(self):
        detected = IntentDetector().detect("what is the weather in Tokyo")
        assert detected.confidence == 0.9, (
            "a single clause without connectors is not a clean split"
        )

    def test_multi_clause_clean_split_is_full_confidence(self):
        detected = IntentDetector().detect("weather in Tokyo and exchange rate USD to PKR")
        assert detected.confidence == 1.0

    def test_single_long_clause_triggers_tier2(self):
        detected = IntentDetector().detect(
            "please fetch the current weather for the city of tokyo together with the humidity today"
        )
        assert detected.confidence == 0.6

    def test_detector_has_no_capability_knowledge(self):
        """The detector must stay pure syntax: its output carries no
        capability names (the bridge lives elsewhere)."""
        detected = IntentDetector().detect("get weather in Tokyo and list pokemon")
        assert len(detected.units) == 2
        assert all("weather" not in u.text or u.text.startswith("get weather") for u in detected.units)


# ---------------------------------------------------------------------------
# B2 / I4 — per-intent IntentCoverage evidence
# ---------------------------------------------------------------------------


class TestB2IntentCoverageEvidence:
    def test_evidence_emitted_per_unit(self, monkeypatch):
        inject_keyword_gc(
            monkeypatch, {"weather": ["get_current_weather"], "pokemon": ["get_pokemon"]}
        )
        nodes = [_node("get_current_weather"), _node("get_pokemon")]
        report = PlanValidatorNode().validate(
            nodes,
            user_query="weather in Tokyo and list pokemon",
            engine_scores={
                "weather in Tokyo": [("get_current_weather", 5.0), ("noise", 3.0)],
                "list pokemon": [("get_pokemon", 100.0)],
            },
        )
        evidence = report.metrics.get("intent_coverage_evidence", [])
        assert len(evidence) == 2, "one record per detected unit"
        by_unit = {rec["unit"]: rec for rec in evidence}
        weather = by_unit["weather in Tokyo"]
        assert weather["classifiable"] is True
        assert "get_current_weather" in weather["candidates"]
        assert weather["best"] == "get_current_weather"
        assert weather["chosen"] == "get_current_weather"
        assert weather["engine_verdict"] == "aligned"
        assert weather["aligned"] is True
        assert weather["served"] is True

    def test_evidence_marks_unclassifiable_units(self, monkeypatch):
        inject_keyword_gc(monkeypatch, {"weather": ["get_current_weather"]})
        nodes = [_node("get_current_weather")]
        report = PlanValidatorNode().validate(
            nodes, user_query="weather in Lahore and what about the book?"
        )
        evidence = {rec["unit"]: rec for rec in report.metrics["intent_coverage_evidence"]}
        book = evidence["what about the book?"]
        assert book["classifiable"] is False
        assert book["candidates"] == []
        assert book["served"] is None

    def test_evidence_flags_misalignment(self, monkeypatch):
        """A served unit whose pick differs from the engine's STRONG top
        candidate (score-based, B3) is misaligned."""
        inject_keyword_gc(
            monkeypatch,
            {
                "weather": ["get_current_weather", "get_weather_clone", "weather_pro"],
                "tokyo": ["get_current_weather"],
            },
        )
        nodes = [_node("weather_pro")]
        report = PlanValidatorNode().validate(
            nodes,
            user_query="weather in Tokyo",
            preferred_tools=["get_current_weather", "get_weather_clone", "weather_pro"],
            engine_scores={"weather in Tokyo": [("get_current_weather", 100.0)]},
        )
        rec = report.metrics["intent_coverage_evidence"][0]
        assert rec["engine_top"] == "get_current_weather"
        assert rec["engine_verdict"] == "misaligned"
        assert rec["chosen"] == "weather_pro"
        assert rec["aligned"] is False


# ---------------------------------------------------------------------------
# B3 — capability alignment blocking after the repair budget
# ---------------------------------------------------------------------------


class TestB3AlignmentBlocking:
    """B3/P0-B semantics (landed, engine-score based): capability alignment
    BLOCKS (ERROR/REFINE) only when the DETERMINISTIC resolver's per-unit
    SCORES establish strong evidence (unique or dominant top candidate vs a
    different pick). Weak/close/absent signals are ambiguous — evidence
    only, never blocking (the historical false positives — scenarios
    8/20/38/47 — lived in weak-signal territory)."""

    @staticmethod
    def _state(op: str, rounds: int) -> dict:
        return {
            "_logical_workflow": {"nodes": [_node(op)]},
            "_plan_validator_rounds": rounds,
            "_preferred_tools": ["get_current_weather", "get_weather_clone", "weather_pro"],
            "messages": [{"role": "user", "content": "weather in Tokyo"}],
        }

    @staticmethod
    def _keywords() -> dict:
        return {
            "weather": ["get_current_weather", "get_weather_clone", "weather_pro"],
            "tokyo": ["get_current_weather"],
        }

    def test_strong_misalignment_is_blocking(self, monkeypatch):
        """A pick that differs from the engine's STRONG (unique) top is an
        ERROR violation — the bounded refine loop repairs it (B3)."""
        inject_keyword_gc(monkeypatch, self._keywords())

        class _FakeEngine:
            async def resolve(self, query, top_k=None):
                class _C:
                    name = "get_current_weather"
                    score = 100.0

                class _R:
                    capability_candidates = [_C()]

                return _R()

        import nexus.capabilities.resolution_engine as _re

        monkeypatch.setattr(_re, "get_resolution_engine", lambda: _FakeEngine())
        out = asyncio.run(PlanValidatorNode()(self._state("weather_pro", rounds=5)))
        report = out["_plan_validator_report"]
        codes = [v["code"] for v in report["violations"]]
        assert "capability_alignment" in codes
        assert all(
            v["severity"] == "error"
            for v in report["violations"]
            if v["code"] == "capability_alignment"
        )

    def test_weak_signal_is_not_blocking(self, monkeypatch):
        """Close/weak engine scores never block — the historical false
        positive class stays protected."""
        inject_keyword_gc(monkeypatch, self._keywords())

        class _FakeEngine:
            async def resolve(self, query, top_k=None):
                class _C:
                    def __init__(self, name, score):
                        self.name = name
                        self.score = score

                class _R:
                    capability_candidates = [_C("get_current_weather", 3.0), _C("noise", 3.0)]

                return _R()

        import nexus.capabilities.resolution_engine as _re

        monkeypatch.setattr(_re, "get_resolution_engine", lambda: _FakeEngine())
        out = asyncio.run(PlanValidatorNode()(self._state("weather_pro", rounds=5)))
        assert out["_plan_validator_action"] in ("proceed",)
        report = out["_plan_validator_report"]
        assert not any(v["code"] == "capability_alignment" for v in report["violations"])
        rec = report["metrics"]["intent_coverage_evidence"][0]
        assert rec["engine_verdict"] == "ambiguous"

    def test_engine_top_pick_is_aligned(self, monkeypatch):
        inject_keyword_gc(monkeypatch, self._keywords())
        out = asyncio.run(PlanValidatorNode()(self._state("get_current_weather", rounds=5)))
        assert out["_plan_validator_action"] == "proceed"
        report = out["_plan_validator_report"]
        assert not any(v["code"] == "capability_alignment" for v in report["violations"])


# ---------------------------------------------------------------------------
# B4 — router backstop
# ---------------------------------------------------------------------------


class _FakeLLM:
    def __init__(self, goals: list[str]) -> None:
        self._goals = goals

    async def complete(self, model=None, messages=None, **kwargs):
        class _R:
            content = json.dumps({"goals": self._goals, "needs_requirements": False})
            failed = False

        return _R()


class _FakeResolution:
    def __init__(self, names: list[str]) -> None:
        self._names = names
        self.has_workflow_candidates = False

    @property
    def capability_candidates(self):
        return [type("C", (), {"name": n})() for n in self._names]


class _FakeEngine:
    def __init__(self, names: list[str]) -> None:
        self._names = names

    async def resolve(self, *args, **kwargs):
        return _FakeResolution(self._names)


class TestB4RouterBackstop:
    @staticmethod
    def _patch_classifier(monkeypatch, goal: str):
        import nexus.agent.router as _router

        async def _fake_classify(**kw):
            return _router.ExecutionGoals(goals=(_router.ExecutionGoal(goal),))

        monkeypatch.setattr(_router, "classify_query", _fake_classify)
        monkeypatch.setattr(
            "nexus.capabilities.resolution_engine.get_resolution_engine",
            lambda: _FakeEngine([]),
        )

    def test_conversational_rerouted_when_executable_evidence(self, monkeypatch):
        inject_keyword_gc(monkeypatch, {"weather": ["get_current_weather"]})
        self._patch_classifier(monkeypatch, "conversation")
        from nexus.agent.router import node_classify_query

        result = asyncio.run(
            node_classify_query(
                {"messages": [{"role": "user", "content": "weather in Tokyo"}]},
                llm=_FakeLLM(["conversation"]),
                model="m",
            )
        )
        assert result["_query_type"] == "action", (
            "deterministic executable evidence overrides the router"
        )

    def test_pure_greeting_stays_conversational(self, monkeypatch):
        inject_keyword_gc(monkeypatch, {"weather": ["get_current_weather"]})
        self._patch_classifier(monkeypatch, "conversation")
        from nexus.agent.router import node_classify_query

        result = asyncio.run(
            node_classify_query(
                {"messages": [{"role": "user", "content": "hi there"}]},
                llm=_FakeLLM(["conversation"]),
                model="m",
            )
        )
        assert result["_query_type"] == "conversation", (
            "no executable evidence -> conversational stands"
        )


# ---------------------------------------------------------------------------
# B5 — iterate_over resolvability (F1 root cause) + PlanCache key
# ---------------------------------------------------------------------------


class TestB5IterateOverValidation:
    def test_phantom_collection_is_a_violation(self):
        report = PlanValidatorNode().validate(
            [_node("get_current_weather", iterate_over="phantom_collection")],
            user_query="weather in cities",
            collections={},
        )
        assert any(v.code == "unresolved_iterate_over" for v in report.violations)
        assert report.valid is False

    def test_declared_non_empty_collection_passes(self):
        report = PlanValidatorNode().validate(
            [_node("get_current_weather", iterate_over="cities")],
            user_query="weather in cities",
            collections={"cities": ["Tokyo", "Osaka"]},
        )
        assert not any(v.code == "unresolved_iterate_over" for v in report.violations)

    def test_runtime_placeholder_collection_passes(self):
        report = PlanValidatorNode().validate(
            [_node("get_current_weather", iterate_over="${StepA.result.posts}")],
            user_query="weather in posts",
            collections={},
        )
        assert not any(v.code == "unresolved_iterate_over" for v in report.violations)


class TestB5PlanCacheKeyShape:
    def test_key_distinguishes_iterate_over_and_collections(self):
        from nexus.compiler.cache import PlanCache

        pc = PlanCache()
        base = {"op": "x", "inputs": {}, "depends_on": []}
        k1 = pc.build_workflow_key({
            "nodes": [{**base, "iterate_over": "a"}],
            "collections": {"a": [1, 2]},
        })
        k2 = pc.build_workflow_key({
            "nodes": [{**base, "iterate_over": "b"}],
            "collections": {"b": [1, 2]},
        })
        k3 = pc.build_workflow_key({
            "nodes": [{**base, "iterate_over": ""}],
            "collections": {},
        })
        assert k1 != k2, "different iterate_over must never share a cached graph"
        assert k2 != k3, "map vs plain tool must never share a cached graph"

