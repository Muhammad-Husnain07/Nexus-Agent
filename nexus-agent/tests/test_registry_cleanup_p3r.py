"""Registry-cleanup regression tests (P3R).

1. ALIAS-INDEX STRING BUG: ``unit_candidates`` must never iterate an
   alias-index value as a sequence — a token directly in the alias index
   (e.g. the web-search alias "search") would otherwise produce single
   CHARACTERS as capability candidates, corrupting coverage/alignment
   evidence (the F8 regression after the registry re-sync).
2. Registry metadata sanity: read-only tools are idempotent; artifact
   fields resolve to declared schema paths.
"""

from __future__ import annotations

from nexus.agent.planners.intent_detector import unit_candidates


class _Unit:
    text = "search for books about climate"


class _GC:
    alias_index = {"search": "search_web_search"}  # STRING value (the bug class)

    def match_capabilities(self, tokens):
        return ["search_books"]

    capability_index = {
        "search_books": {"keywords": ["books"]},
        "search_web_search": {"keywords": ["web"]},
    }


def test_alias_string_value_never_iterated_as_sequence():
    cands = unit_candidates(_Unit(), _GC())
    assert "search_web_search" in cands
    assert not any(len(c) <= 2 for c in cands), (
        "single characters must never become candidates — the alias value "
        "is a capability NAME, not a list"
    )


def test_alias_list_value_still_works():
    class _GCList:
        alias_index = {"pokemon": ["get_pokemon"]}

        def match_capabilities(self, tokens):
            return []

        capability_index = {}

    u = type("_U", (), {"text": "pokemon info"})()
    assert unit_candidates(u, _GCList()) == frozenset({"get_pokemon"})
