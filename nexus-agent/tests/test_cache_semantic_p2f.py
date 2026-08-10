"""P2F SEMANTIC CACHE ELIGIBILITY gate.

A syntactically valid plan is NOT semantically safe to cache. The planner
writes the parse cache BEFORE validation, so the semantic verdict gates
the cache via the VALIDATOR/COMPILER as gatekeepers: any entry whose
verdict is not cache-eligible is REMOVED the moment it is rejected.

Eligibility (the cache may hold a plan only when ALL hold):

- validator report VALID (REFINE/ABORT verdicts are never eligible);
- intent coverage == 100% (partial-execution plans never replayed);
- no capability_alignment violation;
- structural safety (I11 schema/provenance) at write time (planner);
- compilation succeeds (compiler removes on failure).

Reads are already revalidated: the validator runs after EVERY cache hit,
and a rejected cached entry is removed (self-healing — pre-rule entries
disappear the first time they are rejected).
"""

from __future__ import annotations

from tests.helpers import inject_keyword_gc

import asyncio

import pytest

from nexus.agent.nodes.plan_validator_node import (
    PlanValidatorNode,
    PlanValidatorReport,
    _semantic_cache_eligible,
)


def _report(valid: bool, coverage: float = 1.0, alignment_violation: bool = False) -> PlanValidatorReport:
    from nexus.agent.nodes.plan_validator_node import (
        Violation,
        ViolationAction,
        ViolationSeverity,
    )

    violations = []
    if alignment_violation:
        violations.append(Violation(
            code="capability_alignment",
            severity=ViolationSeverity.ERROR,
            action=ViolationAction.REFINE,
            node="plan",
            message="m",
        ))
    return PlanValidatorReport(
        valid=valid,
        violations=tuple(violations),
        errors=["x"] if not valid else [],
        metrics={"intent_coverage": coverage},
    )


# ---------------------------------------------------------------------------
# 1. the eligibility contract
# ---------------------------------------------------------------------------


def test_eligible_only_when_valid_full_coverage_no_alignment():
    assert _semantic_cache_eligible(_report(True, 1.0, False)) is True


def test_invalid_report_never_eligible():
    assert _semantic_cache_eligible(_report(False, 1.0, False)) is False


def test_partial_coverage_never_eligible():
    assert _semantic_cache_eligible(_report(True, 0.5, False)) is False
    assert _semantic_cache_eligible(_report(True, 0.0, False)) is False


def test_alignment_violation_never_eligible():
    assert _semantic_cache_eligible(_report(True, 1.0, True)) is False


# ---------------------------------------------------------------------------
# 2. validator gatekeeper wiring
# ---------------------------------------------------------------------------


class _SpyCache:
    def __init__(self):
        self.removed: list[tuple] = []

    async def remove(self, query, tools, model, context=""):
        self.removed.append((query, context))


def inject_keyword_gc(monkeypatch, mapping: dict[str, list[str]]) -> None:
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


def _node(op: str) -> dict:
    return {"op": op, "inputs": {}, "depends_on": []}


def _state(query: str, nodes: list[dict], **extra) -> dict:
    s = {
        "_logical_workflow": {"nodes": nodes},
        "_plan_validator_rounds": 0,
        "messages": [{"role": "user", "content": query}],
    }
    s.update(extra)
    return s


def test_rejected_plan_removed_from_cache(monkeypatch):
    """A coverage-rejected plan (REFINE) must be REMOVED from the parse
    cache — the exact entry the planner wrote."""
    spy = _SpyCache()
    monkeypatch.setattr(
        "nexus.compiler.cache.get_parse_cache", lambda: spy
    )
    inject_keyword_gc(
        monkeypatch,
        {"weather": ["get_current_weather"], "pokemon": ["get_pokemon"]},
    )
    # plan covers only the weather intent → pokemon dropped → refine
    state = _state("weather in Tokyo and list pokemon", [_node("get_current_weather")])
    out = asyncio.run(PlanValidatorNode()(state))
    assert out["_plan_validator_action"] == "refine"
    assert spy.removed, "a REFINE verdict must remove the cached entry"
    assert spy.removed[0][0] == "weather in Tokyo and list pokemon"


def test_partial_execution_proceed_removed_from_cache(monkeypatch):
    """The partial-execution PROCEED (coverage < 100% after bounded repair)
    is NOT cache-eligible — its entry must be removed."""
    spy = _SpyCache()
    monkeypatch.setattr("nexus.compiler.cache.get_parse_cache", lambda: spy)
    inject_keyword_gc(
        monkeypatch,
        {"weather": ["get_current_weather"], "pokemon": ["get_pokemon"]},
    )
    state = _state(
        "weather in Tokyo and list pokemon",
        [_node("get_current_weather")],
        _plan_validator_rounds=5,  # repair budget exhausted → partial proceed
    )
    out = asyncio.run(PlanValidatorNode()(state))
    assert out["_plan_validator_action"] == "proceed"
    assert spy.removed, "a partial-execution plan must not persist in the cache"


def test_pass_plan_stays_in_cache(monkeypatch):
    """A full-coverage valid plan is cache-eligible — NOT removed."""
    spy = _SpyCache()
    monkeypatch.setattr("nexus.compiler.cache.get_parse_cache", lambda: spy)
    inject_keyword_gc(
        monkeypatch,
        {"weather": ["get_current_weather"], "pokemon": ["get_pokemon"]},
    )
    state = _state(
        "weather in Tokyo and list pokemon",
        [_node("get_current_weather"), _node("get_pokemon")],
        _plan_validator_rounds=5,
    )
    out = asyncio.run(PlanValidatorNode()(state))
    assert out["_plan_validator_action"] == "proceed"
    assert spy.removed == [], "a cache-eligible plan must never be removed"


def test_old_cached_entry_self_heals(monkeypatch):
    """A PRE-RULE entry (e.g. F8's cached 1-op plan) is removed the first
    time it is rejected — the cache self-heals without a migration."""
    spy = _SpyCache()
    monkeypatch.setattr("nexus.compiler.cache.get_parse_cache", lambda: spy)
    inject_keyword_gc(
        monkeypatch,
        {"weather": ["get_current_weather"], "pokemon": ["get_pokemon"]},
    )
    state = _state("weather in Tokyo and list pokemon", [_node("get_current_weather")])
    asyncio.run(PlanValidatorNode()(state))
    assert len(spy.removed) == 1
    # the next session now MISSES and plans fresh (removal is the fix)
    assert spy.removed[0][0] == "weather in Tokyo and list pokemon"


# ---------------------------------------------------------------------------
# 3. removal helper (key replication)
# ---------------------------------------------------------------------------


def test_removal_helper_uses_full_key_components(monkeypatch):
    """The removal key must replicate the planner's key: query + prior
    chain context + model. A wrong key would leave the bad entry behind."""
    from nexus.agent.nodes.plan_validator_node import _remove_semantically_ineligible_plan

    spy = _SpyCache()
    monkeypatch.setattr("nexus.compiler.cache.get_parse_cache", lambda: spy)
    state = {
        "messages": [{"role": "user", "content": "weather in Tokyo"}],
        "_execution_graph": {
            "nodes": {"n1": {"tool_name": "get_current_weather"}}
        },
    }
    asyncio.run(_remove_semantically_ineligible_plan(state, "test"))
    assert len(spy.removed) == 1
    query, context = spy.removed[0]
    assert query == "weather in Tokyo"
    assert "get_current_weather" in context  # prior chain rides the key


def test_removal_helper_degrade_safe(monkeypatch):
    """Any failure in the removal must leave the entry in place (never
    crash validation)."""
    from nexus.agent.nodes.plan_validator_node import _remove_semantically_ineligible_plan

    async def _boom(*a, **k):
        raise RuntimeError("cache down")

    monkeypatch.setattr("nexus.compiler.cache.get_parse_cache", lambda: type("C", (), {"remove": _boom})())
    asyncio.run(_remove_semantically_ineligible_plan({"messages": [{"role": "user", "content": "q"}]}, "test"))


# ---------------------------------------------------------------------------
# 4. compiler failure removes the entry
# ---------------------------------------------------------------------------


def test_compiler_failure_removes_parse_entry(monkeypatch):
    """A plan that fails compilation must be removed from the parse cache
    (compile success is part of the eligibility contract)."""
    from nexus.agent.nodes.compiler_node import compiler_node

    spy = _SpyCache()
    monkeypatch.setattr("nexus.compiler.cache.get_parse_cache", lambda: spy)

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("nexus.db.base.async_session", lambda: _FakeSession())

    class _BoomCompiler:
        def __init__(self, *a, **k):
            pass

        async def compile(self, lw, resolver_context=None):
            raise RuntimeError("implicit placeholder cycle")

    monkeypatch.setattr("nexus.agent.nodes.compiler_node.Compiler", _BoomCompiler)

    state = {
        "messages": [{"role": "user", "content": "weather in Tokyo"}],
        "_logical_workflow": {"nodes": [{"op": "get_current_weather", "ref": "n1", "inputs": {}, "depends_on": []}]},
        "_compile_retry_count": 0,
    }
    patch = asyncio.run(compiler_node(state))  # @context_node wrapper expects the state dict
    assert patch.get("_compile_errors")
    assert spy.removed, "a compile failure must remove the parse-cache entry"
    assert spy.removed[0][0] == "weather in Tokyo"


@pytest.mark.parametrize("rounds", [0, 1])
def test_compile_abort_path_also_removes(monkeypatch, rounds):
    from nexus.agent.nodes.compiler_node import compiler_node

    spy = _SpyCache()
    monkeypatch.setattr("nexus.compiler.cache.get_parse_cache", lambda: spy)

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("nexus.db.base.async_session", lambda: _FakeSession())

    class _BoomCompiler:
        def __init__(self, *a, **k):
            pass

        async def compile(self, lw, resolver_context=None):
            raise RuntimeError("boom")

    monkeypatch.setattr("nexus.agent.nodes.compiler_node.Compiler", _BoomCompiler)
    state = {
        "messages": [{"role": "user", "content": "weather in Tokyo"}],
        "_logical_workflow": {"nodes": [{"op": "get_current_weather", "ref": "n1", "inputs": {}, "depends_on": []}]},
        "_compile_retry_count": 3,  # bound exhausted → abort path
    }
    patch = asyncio.run(compiler_node(state))
    assert patch.get("_compile_errors")
    assert spy.removed
