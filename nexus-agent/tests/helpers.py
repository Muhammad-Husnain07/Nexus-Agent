"""Shared test helpers (P3 consolidation).

Helpers that were duplicated across stage test files with identical
behavior live here once:
- ``inject_keyword_gc`` — the fake GlobalContext shape (keyword map,
  O(1) keyword index, alias index) used by the plan validator / planner
  tests.
- ``node`` — the minimal logical-plan node dict.
"""

from __future__ import annotations


def inject_keyword_gc(monkeypatch, mapping: dict[str, list[str]]) -> None:
    """Fake GlobalContext mirroring the real shape (keyword map keyed by
    capability name; O(1) keyword index; alias index)."""
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


def node(op: str, **extra) -> dict:
    n = {"op": op, "inputs": {}, "depends_on": []}
    n.update(extra)
    return n
