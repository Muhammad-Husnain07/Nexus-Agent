"""D0/P0-D — F4 cache-poisoning prevention + I11.

Invariant I11: a plan failing structural/input-schema validation MUST NOT
be persisted to the ParseCache and MUST NOT cross the compiler→executor
boundary. The F4 failure class (scenario 35) proved that an invalid LLM
plan could be cached and replayed deterministically.
"""

from __future__ import annotations

from nexus.agent.nodes.compiler_node import _graph_has_unknown_input_keys
from nexus.agent.nodes.plan_validator_node import PlanValidatorNode
from nexus.agent.nodes.semantic_parser_node import _plan_unsafe_to_cache


def _inject_gc(monkeypatch, schema, aliases=None, required=None):
    """GC meta: one capability with a declared input schema (+aliases)."""
    import nexus.agent.nodes.plan_validator_node as pv
    import nexus.context.global_context as gc_mod

    props = {k: {"type": "string"} for k in (schema or [])}
    if aliases:
        for prop_name, alist in aliases.items():
            props.setdefault(prop_name, {})["x-aliases"] = alist

    meta = {
        "input_schema": {
            "type": "object", "properties": props, "required": required or [],
        },
        "input_required": list(required or []),
        "input_aliases": {
            k: v for k, v in (aliases or {}).items()
        },
        "produces": [],
        "consumes": [],
        "keywords": [],
    }

    class _GC:
        capability_index = {"known_op": meta}
        capability_keywords = {"known": ["known_op"]}
        capability_providers = {}
        alias_index = {}
        compiled_graph = None

        def match_capabilities(self, tokens):
            return ["known_op"]

    monkeypatch.setattr(pv._gc_mod, "get_global_context", lambda: _GC())
    monkeypatch.setattr(gc_mod, "get_global_context", lambda: _GC())


def _node(op: str = "known_op", inputs: dict | None = None) -> dict:
    return {"op": op, "ref": "StepA", "inputs": inputs or {}, "depends_on": []}


class TestValidatorUnknownInputKeys:
    def test_invented_key_is_a_violation(self, monkeypatch):
        _inject_gc(monkeypatch, schema=["city", "unit"], required=["unit"])
        report = PlanValidatorNode().validate([_node(inputs={"city": "Tokyo", "banana": 1})])
        codes = [v.code for v in report.violations]
        assert "unknown_input_key" in codes
        assert report.valid is False

    def test_declared_keys_pass(self, monkeypatch):
        _inject_gc(monkeypatch, schema=["city", "unit"], required=["unit"])
        report = PlanValidatorNode().validate([_node(inputs={"city": "Tokyo", "unit": "c"})])
        assert not any(v.code == "unknown_input_key" for v in report.violations)

    def test_x_alias_key_is_accepted(self, monkeypatch):
        _inject_gc(monkeypatch, schema=["city"], aliases={"city": ["city_name"]})
        report = PlanValidatorNode().validate([_node(inputs={"city_name": "Tokyo"})])
        assert not any(v.code == "unknown_input_key" for v in report.violations)

    def test_no_schema_never_guesses(self, monkeypatch):
        _inject_gc(monkeypatch, schema=[])
        report = PlanValidatorNode().validate([_node(inputs={"anything": 1})])
        assert not any(v.code == "unknown_input_key" for v in report.violations)


class TestParseCacheGuard:
    def test_invented_keys_never_cached(self, monkeypatch):
        _inject_gc(monkeypatch, schema=["city"])
        assert _plan_unsafe_to_cache([_node(inputs={"city": "Tokyo", "junk": 1})]) is True

    def test_clean_plan_cacheable(self, monkeypatch):
        _inject_gc(monkeypatch, schema=["city"])
        assert _plan_unsafe_to_cache([_node(inputs={"city": "Tokyo"})]) is False

    def test_empty_plan_cacheable(self, monkeypatch):
        _inject_gc(monkeypatch, schema=["city"])
        assert _plan_unsafe_to_cache([]) is False

    def test_unprovable_required_value_never_cached(self, monkeypatch):
        """I11 extension (P1-A): a REQUIRED input with a literal value not
        traceable to the user message is a guessed value — caching it
        replays the guess deterministically (the scenario-35 base_currency
        replay class)."""
        _inject_gc(monkeypatch, schema=["city", "unit"], required=["unit"])
        # unit is required; "banana" is nowhere in the message
        plan = [_node(inputs={"city": "Tokyo", "unit": "banana"})]
        assert _plan_unsafe_to_cache(plan, user_query="weather in Tokyo") is True

    def test_provable_required_value_cacheable(self, monkeypatch):
        _inject_gc(monkeypatch, schema=["city", "unit"], required=["unit"])
        plan = [_node(inputs={"city": "Tokyo", "unit": "c"})]
        assert _plan_unsafe_to_cache(plan, user_query="weather in Tokyo in c") is False

    def test_placeholder_required_value_cacheable(self, monkeypatch):
        """Producer-chain placeholders are valid cacheable references."""
        _inject_gc(monkeypatch, schema=["city", "unit"], required=["unit"])
        plan = [_node(inputs={"city": "${StepA.result.city}", "unit": "c"})]
        assert _plan_unsafe_to_cache(plan, user_query="weather in Tokyo in c") is False


class TestCompilerCacheBackstop:
    def test_cached_graph_with_invented_keys_rejected(self, monkeypatch):
        _inject_gc(monkeypatch, schema=["city"])
        graph = {
            "nodes": {
                "n1": {
                    "kind": "tool",
                    "capability": "known_op",
                    "tool_name": "known_op",
                    "inputs": {"city": "Tokyo", "junk": 1},
                }
            }
        }
        assert _graph_has_unknown_input_keys(graph) is True

    def test_cached_graph_clean_accepted(self, monkeypatch):
        _inject_gc(monkeypatch, schema=["city"])
        graph = {
            "nodes": {
                "n1": {
                    "kind": "tool",
                    "capability": "known_op",
                    "tool_name": "known_op",
                    "inputs": {"city": "Tokyo"},
                }
            }
        }
        assert _graph_has_unknown_input_keys(graph) is False

    def test_non_tool_nodes_ignored(self, monkeypatch):
        _inject_gc(monkeypatch, schema=["city"])
        graph = {
            "nodes": {
                "m1": {"kind": "map", "iterate_over": "c", "body": {}},
                "r1": {"kind": "reduce", "source_ref": "c"},
            }
        }
        assert _graph_has_unknown_input_keys(graph) is False

