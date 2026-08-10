"""F8-B EVIDENCE-DIRECTED PLANNER REPAIR gate.

The F8 mechanism: the LLM extraction mis-resolves the second of two
parallel intents to the FIRST capability (both "list X" intents →
get_ghibli_films), and replan feedback that only names the unit TEXT does
not fix a CAPABILITY disambiguation error. The deterministic validator
already computed the correct per-unit candidate capabilities.

F8-B surfaces those deterministic candidate NAMES into the replan prompt:

    UNCOVERED INTENT: "list Valorant agents"
    DETERMINISTIC CAPABILITY CANDIDATES (registered capabilities only):
      - get_valorant_agents
      ...
    REQUIREMENT: create an operation for EACH uncovered intent ...

Constraints enforced here:

- Candidate names ONLY (no scores, no ranking internals).
- Candidates filtered to valid_ops — no arbitrary LLM-generated capabilities.
- Only uncovered (served=False), classifiable, non-negated intents.
- Empty/absent evidence → EXACTLY the pre-F8-B behavior (None).
- Deterministic output for identical state.
- No cache change, no repair-round change, no new node, no first-pass change.
"""

from __future__ import annotations

import pytest

from nexus.agent.nodes.semantic_parser_node import (
    _coverage_evidence_feedback,
    _coverage_uncovered_candidates,
)

VALID_OPS = [
    "get_ghibli_films",
    "get_valorant_agents",
    "general_list_datasources",
    "general_list_tables",
]

COVERED = {
    "unit": "List Studio Ghibli films",
    "negated": False,
    "classifiable": True,
    "served": True,
    "candidates": ["general_list_datasources", "general_list_tables", "get_ghibli_films"],
}

UNCOVERED = {
    "unit": "list Valorant agents",
    "negated": False,
    "classifiable": True,
    "served": False,
    "candidates": ["general_list_datasources", "general_list_tables", "get_valorant_agents"],
}


def _snapshot(errors: list[str], evidence: list[dict]) -> dict:
    return {
        "_plan_validator_errors": errors,
        "_plan_validator_report": {"metrics": {"intent_coverage_evidence": evidence}},
    }


def _cov_errors() -> list[str]:
    return ["intent coverage 50% (1 dropped): list Valorant agents"]


# ---------------------------------------------------------------------------
# 1. uncovered intent gets candidate names
# ---------------------------------------------------------------------------


def test_uncovered_intent_gets_candidate_names():
    note = _coverage_evidence_feedback(
        _snapshot(_cov_errors(), [COVERED, UNCOVERED]), VALID_OPS
    )
    assert note is not None
    assert "list Valorant agents" in note
    assert "get_valorant_agents" in note
    assert "UNCOVERED INTENT" in note


def test_covered_intent_gets_no_candidate_feedback():
    """Already-served intents must not receive candidate feedback."""
    note = _coverage_evidence_feedback(
        _snapshot(_cov_errors(), [COVERED]), VALID_OPS
    )
    assert note is None


# ---------------------------------------------------------------------------
# 2. multiple candidates preserved
# ---------------------------------------------------------------------------


def test_multiple_candidates_preserved():
    note = _coverage_evidence_feedback(
        _snapshot(_cov_errors(), [UNCOVERED]), VALID_OPS
    )
    assert note is not None
    for cand in ("get_valorant_agents", "general_list_tables", "general_list_datasources"):
        assert f"- {cand}" in note


# ---------------------------------------------------------------------------
# 3. empty candidate list → existing behavior
# ---------------------------------------------------------------------------


def test_empty_candidates_returns_none():
    rec = dict(UNCOVERED, candidates=[])
    assert (
        _coverage_evidence_feedback(_snapshot(_cov_errors(), [rec]), VALID_OPS)
        is None
    )
    rec2 = dict(UNCOVERED, candidates=None)
    assert (
        _coverage_evidence_feedback(_snapshot(_cov_errors(), [rec2]), VALID_OPS)
        is None
    )


def test_no_coverage_error_returns_none():
    """A non-coverage rejection (e.g. schema error) must not trigger the
    evidence block — first-pass/other-repair behavior unchanged."""
    assert (
        _coverage_evidence_feedback(
            _snapshot(["schema violation: bad input"], [UNCOVERED]), VALID_OPS
        )
        is None
    )


def test_missing_report_returns_none():
    assert _coverage_evidence_feedback({"_plan_validator_errors": _cov_errors()}, VALID_OPS) is None


def test_empty_valid_ops_returns_none():
    assert _coverage_evidence_feedback(_snapshot(_cov_errors(), [UNCOVERED]), []) is None


# ---------------------------------------------------------------------------
# 4. no arbitrary LLM-generated capabilities
# ---------------------------------------------------------------------------


def test_candidates_filtered_to_valid_ops():
    """A capability NOT in valid_ops (unregistered/disabled/hallucinated)
    must never reach the prompt."""
    rec = dict(
        UNCOVERED,
        candidates=["get_valorant_agents", "mystery_hallucinated_tool", "general_list_tables"],
    )
    note = _coverage_evidence_feedback(_snapshot(_cov_errors(), [rec]), VALID_OPS)
    assert note is not None
    assert "mystery_hallucinated_tool" not in note
    assert "get_valorant_agents" in note


def test_all_candidates_filtered_returns_none():
    rec = dict(UNCOVERED, candidates=["mystery_tool_a", "mystery_tool_b"])
    assert _coverage_evidence_feedback(_snapshot(_cov_errors(), [rec]), VALID_OPS) is None


# ---------------------------------------------------------------------------
# 5. determinism
# ---------------------------------------------------------------------------


def test_candidate_feedback_deterministic():
    a = _coverage_evidence_feedback(_snapshot(_cov_errors(), [UNCOVERED]), VALID_OPS)
    b = _coverage_evidence_feedback(_snapshot(_cov_errors(), [UNCOVERED]), VALID_OPS)
    assert a == b


# ---------------------------------------------------------------------------
# 6. duplicate candidates handled
# ---------------------------------------------------------------------------


def test_duplicate_candidates_deduped():
    rec = dict(
        UNCOVERED,
        candidates=["get_valorant_agents", "get_valorant_agents", "general_list_tables"],
    )
    note = _coverage_evidence_feedback(_snapshot(_cov_errors(), [rec]), VALID_OPS)
    assert note.count("- get_valorant_agents") == 1


# ---------------------------------------------------------------------------
# 7. negative / unclassifiable intents never fed
# ---------------------------------------------------------------------------


def test_negated_uncovered_intent_not_fed():
    rec = dict(UNCOVERED, negated=True, unit="not list valorant agents")
    assert _coverage_evidence_feedback(_snapshot(_cov_errors(), [rec]), VALID_OPS) is None


def test_unclassifiable_uncovered_intent_not_fed():
    rec = dict(UNCOVERED, classifiable=False)
    assert _coverage_evidence_feedback(_snapshot(_cov_errors(), [rec]), VALID_OPS) is None


# ---------------------------------------------------------------------------
# 8. I11 provenance preserved — the repair never writes the cache
# ---------------------------------------------------------------------------


def test_repair_does_not_touch_cache_gate(monkeypatch):
    """The evidence feedback is read-only: it must not write, read, or
    bypass the ParseCache, and the structural cache gate (I11) is
    untouched — a covered-plan cache write path remains the only writer."""
    from nexus.agent.nodes import semantic_parser_node as sp

    set_called = False
    original_set = sp.get_parse_cache().set

    async def _spy(*a, **k):
        nonlocal set_called
        set_called = True
        return await original_set(*a, **k)

    monkeypatch.setattr(sp.get_parse_cache(), "set", _spy)
    note = _coverage_evidence_feedback(_snapshot(_cov_errors(), [UNCOVERED]), VALID_OPS)
    assert note is not None
    assert set_called is False, "evidence feedback must not write the cache"


def test_no_deterministic_synthesis_in_repair():
    """F8-B is evidence-only: the helper returns a STRING block, never a
    synthesized node — the planner still constructs operations."""
    note = _coverage_evidence_feedback(_snapshot(_cov_errors(), [UNCOVERED]), VALID_OPS)
    assert isinstance(note, str)
    assert '"op"' not in (note or "")
    assert "inputs" not in (note or "")


# ---------------------------------------------------------------------------
# 9. STRUCTURAL SCOPE WIDENING — the F8 mechanism fix
# ---------------------------------------------------------------------------

_REG = {"get_valorant_agents": {"x": 1}, "general_list_tables": {"x": 1}, "get_ghibli_films": {"x": 1}}


@pytest.fixture(autouse=True)
def _reg_meta(monkeypatch):
    monkeypatch.setattr(
        "nexus.agent.nodes.plan_validator_node._capability_meta",
        lambda c: dict(_REG.get(c) or {}),
    )


def test_uncovered_candidates_returned():
    cands = _coverage_uncovered_candidates(
        _snapshot(_cov_errors(), [COVERED, UNCOVERED]), VALID_OPS
    )
    assert "get_valorant_agents" in cands
    assert "general_list_tables" in cands
    assert "general_list_datasources" not in cands  # not in the registry fake
    assert "get_ghibli_films" not in cands  # covered unit contributes nothing


def test_uncovered_candidates_deterministic_deduped():
    rec = dict(UNCOVERED, candidates=["get_valorant_agents", "general_list_tables", "get_valorant_agents"])
    a = _coverage_uncovered_candidates(_snapshot(_cov_errors(), [rec]), VALID_OPS)
    b = _coverage_uncovered_candidates(_snapshot(_cov_errors(), [rec]), VALID_OPS)
    assert a == b
    assert a == sorted(set(a))


def test_uncovered_candidates_none_when_no_gap():
    assert _coverage_uncovered_candidates(_snapshot(_cov_errors(), [COVERED]), VALID_OPS) == []
    assert _coverage_uncovered_candidates(_snapshot(["schema error"], [UNCOVERED]), VALID_OPS) == []


def test_scope_widening_enables_the_note():
    """Integration: with a NARROW valid_ops (the F8 condition — the query-
    level resolution barred the second capability), the widening helper
    adds the uncovered candidates so the evidence note can name them."""
    narrow = ["get_ghibli_films"]
    assert _coverage_evidence_feedback(_snapshot(_cov_errors(), [UNCOVERED]), narrow) is None
    cands = _coverage_uncovered_candidates(_snapshot(_cov_errors(), [UNCOVERED]), narrow)
    assert "get_valorant_agents" in cands
    widened = list(dict.fromkeys([*narrow, *cands]))
    note = _coverage_evidence_feedback(_snapshot(_cov_errors(), [UNCOVERED]), widened)
    assert note is not None
    assert "get_valorant_agents" in note


def test_scope_widening_registry_validated():
    """Candidates must be REGISTERED capabilities — an op absent from the
    capability index is never injected into the structural scope."""
    rec = dict(UNCOVERED, candidates=["get_valorant_agents", "not_a_real_op"])
    cands = _coverage_uncovered_candidates(_snapshot(_cov_errors(), [rec]), VALID_OPS)
    assert "not_a_real_op" not in cands
    assert "get_valorant_agents" in cands


def test_scope_widening_skips_negated_and_unclassifiable():
    rec_n = dict(UNCOVERED, negated=True)
    rec_u = dict(UNCOVERED, classifiable=False)
    assert _coverage_uncovered_candidates(_snapshot(_cov_errors(), [rec_n]), VALID_OPS) == []
    assert _coverage_uncovered_candidates(_snapshot(_cov_errors(), [rec_u]), VALID_OPS) == []
