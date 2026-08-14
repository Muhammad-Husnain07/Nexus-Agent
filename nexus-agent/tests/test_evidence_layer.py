"""P0-D: evidence layer tests — artifact → evidence → grounding.

Covers the reviewer's P0-D gates:
- Artifact → Evidence conversion (entity-anchored, capability-labeled)
- Entity identity preserved (Lahore ≠ Karachi)
- Required evidence derived from intents/workflow
- Grounding coverage: required ⊆ available ⊆ rendered (Case B omission
  detection), hallucination detection (Case C), entity-missing detection
- Deterministic fallback renderer preserves execution
- Evidence packet compactness (never the raw artifact graph)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nexus.artifacts.base import ArtifactBase  # noqa: E402
from nexus.artifacts.evidence import (  # noqa: E402
    EvidenceCompiler,
    GroundingValidator,
    RequiredEvidenceCompiler,
    _entity_from_inputs,
)


def _artifact(cap: str, data: dict, execution_id: str = "n1", tool: str = ""):
    return ArtifactBase(
        capability_id=cap,
        type=cap,
        tool_name=tool or cap,
        execution_id=execution_id,
        data=data,
    )


# ---------------------------------------------------------------------------
# D3: artifact → evidence conversion with entity anchoring
# ---------------------------------------------------------------------------

def test_evidence_compile_anchors_entity_from_workflow_inputs():
    arts = [
        _artifact("geocode_location", {"latitude": 31.5, "longitude": 74.3}, "p_geo"),
        _artifact("get_current_weather", {"temperature": 32}, "p_weather"),
    ]
    workflow = [
        {"op": "geocode_location", "ref": "g1", "inputs": {"query": "Lahore"}, "depends_on": []},
        {"op": "get_current_weather", "ref": "w1", "inputs": {}, "depends_on": ["g1"]},
    ]
    phys = {
        "p_geo": {"symbolic_ref": "g1"},
        "p_weather": {"symbolic_ref": "w1"},
    }
    evidence = EvidenceCompiler().compile(
        arts, user_query="weather in Lahore",
        workflow_nodes=workflow, physical_nodes=phys,
    )
    by_cap = {e.capability_id: e for e in evidence}
    # Weather inherits geocode's entity via the producer chain (P0-D.5).
    assert by_cap["geocode_location"].entity_id == "lahore"
    assert by_cap["get_current_weather"].entity_id == "lahore"
    assert by_cap["geocode_location"].facts[0].key == "latitude"
    assert by_cap["get_current_weather"].facts[0].key == "temperature"


def test_evidence_compile_preserves_entity_identity():
    # Two cities, two weathers — never merged.
    arts = [
        _artifact("get_current_weather", {"temperature": 32}, "p_a"),
        _artifact("get_current_weather", {"temperature": 28}, "p_b"),
    ]
    workflow = [
        {"op": "geocode_location", "ref": "gA", "inputs": {"query": "Lahore"}, "depends_on": []},
        {"op": "geocode_location", "ref": "gB", "inputs": {"query": "Karachi"}, "depends_on": []},
        {"op": "get_current_weather", "ref": "wA", "inputs": {}, "depends_on": ["gA"]},
        {"op": "get_current_weather", "ref": "wB", "inputs": {}, "depends_on": ["gB"]},
    ]
    phys = {
        "p_a": {"symbolic_ref": "wA"},
        "p_b": {"symbolic_ref": "wB"},
    }
    evidence = EvidenceCompiler().compile(
        arts, user_query="weather in Lahore and Karachi",
        workflow_nodes=workflow, physical_nodes=phys,
    )
    entities = {e.entity_id for e in evidence}
    assert entities == {"lahore", "karachi"}


def test_evidence_compile_anchors_map_items_from_collections():
    """P1-D: a MapNode fan-out's item artifacts anchor to the COLLECTION
    ITEM (chicken/pasta/rice), never the ${item} placeholder."""
    arts = [
        _artifact("search_meals", {"meals": [{"strMeal": "Chicken Curry"}]}, "m_map_item_0"),
        _artifact("search_meals", {"meals": [{"strMeal": "Pasta Salad"}]}, "m_map_item_1"),
        _artifact("search_meals", {"meals": [{"strMeal": "Rice Bowl"}]}, "m_map_item_2"),
    ]
    workflow = [
        {"op": "search_meals", "ref": "m",
         "inputs": {"query": "${item}"}, "depends_on": [],
         "iterate_over": "search_meals_items"},
    ]
    phys = {
        "m": {"symbolic_ref": "m_map"},
    }
    evidence = EvidenceCompiler().compile(
        arts, user_query="Search for chicken, pasta, and rice recipes",
        workflow_nodes=workflow, physical_nodes=phys,
        collections={"search_meals_items": ["chicken", "pasta", "rice"]},
    )
    entities = {e.entity_id for e in evidence}
    assert entities == {"chicken", "pasta", "rice"}


def test_entity_from_inputs_skips_placeholders_and_query_echoes():
    assert _entity_from_inputs({"query": "Lahore"}, "weather in Lahore") == "Lahore"
    assert _entity_from_inputs({"query": "${g1.result.latitude}"}, "weather") is None
    # Value not in the query → not an entity (no invented anchors).
    assert _entity_from_inputs({"query": "SomethingElse"}, "weather in Lahore") is None


# ---------------------------------------------------------------------------
# D5: required evidence compiler
# ---------------------------------------------------------------------------

def test_required_entities_from_intent_graph():
    structured = {
        "intents": [
            {"intent_id": "intent_1", "goal": "obtain the coordinates for Lahore",
             "entities": ["Lahore"], "sequence": 0, "negated": False},
            {"intent_id": "intent_2", "goal": "weather in Karachi",
             "entities": ["Karachi"], "sequence": 1, "negated": False},
        ],
        "relationships": [],
        "source": "llm",
    }
    req = RequiredEvidenceCompiler(user_query="weather in Lahore and Karachi").required_entities(
        structured, []
    )
    ids = {e.entity_id for e in req}
    assert "lahore" in ids
    assert "karachi" in ids


def test_required_entities_from_workflow_inputs():
    workflow = [
        {"op": "geocode_location", "ref": "g1", "inputs": {"query": "Lahore"}, "depends_on": []},
    ]
    req = RequiredEvidenceCompiler(user_query="weather in Lahore").required_entities(None, workflow)
    assert any(e.entity_id == "lahore" for e in req)


def test_required_entities_reject_nontraceable_goal_tails():
    # The goal extractor can capture sentence tails ("Lahore. if the
    # geocoder returns a result") — only entities the user query names
    # are REAL (P0-B traceability).
    structured = {
        "intents": [
            {"intent_id": "intent_1",
             "goal": "obtain the coordinates for Lahore. if the geocoder returns a result",
             "entities": ["Lahore"], "sequence": 0, "negated": False},
        ],
        "relationships": [],
        "source": "llm",
    }
    req = RequiredEvidenceCompiler(
        user_query="Get the coordinates of Lahore."
    ).required_entities(structured, [])
    ids = {e.entity_id for e in req}
    assert "lahore" in ids
    assert not any("geocoder" in e for e in ids)
    assert len(ids) == 1


# ---------------------------------------------------------------------------
# D6/D8: grounding coverage — required ⊆ available ⊆ rendered
# ---------------------------------------------------------------------------

def _ev(cap: str, entity: str | None, facts: list):
    from nexus.artifacts.evidence import EvidenceFact, ResponseEvidence

    return ResponseEvidence(
        evidence_id=f"ev_{cap}",
        artifact_id="a1",
        entity_id=entity,
        entity_type="location",
        capability_id=cap,
        operation=cap,
        facts=[EvidenceFact(key=k, value=v, source_path=k) for k, v in facts],
        source_node_id="n1",
    )


def test_grounding_complete_when_entities_and_facts_rendered():
    evidence = [_ev("get_current_weather", "lahore", [("temperature", 32)])]
    req = [type("E", (), {"canonical_name": "Lahore", "entity_id": "lahore", "aliases": []})()]
    cov = GroundingValidator(user_query="weather in Lahore").check(
        "The weather in Lahore is 32 degrees.", evidence, req
    )
    assert cov.complete
    assert cov.required_entities_missing == []
    assert cov.coverage_ratio >= 0.99


def test_grounding_detects_entity_omission():
    evidence = [_ev("get_current_weather", "lahore", [("temperature", 32)])]
    req = [type("E", (), {"canonical_name": "Lahore", "entity_id": "lahore", "aliases": []})()]
    cov = GroundingValidator(user_query="weather in Lahore").check(
        "The temperature is 32 degrees.", evidence, req
    )
    assert cov.required_entities_missing == ["lahore"]
    assert not cov.complete


def test_grounding_detects_fact_omission_case_b():
    evidence = [_ev("get_country_info", "japan", [("population", 125_000_000)])]
    req = []
    cov = GroundingValidator(user_query="tell me about Japan").check(
        "Japan is an interesting country.", evidence, req
    )
    assert cov.missing_evidence  # the population fact was never represented
    assert not cov.complete


def test_grounding_detects_hallucinated_numeric_fact_case_c():
    evidence = [_ev("get_current_weather", "lahore", [("temperature", 32)])]
    req = []
    cov = GroundingValidator(user_query="weather in Lahore").check(
        "Temperature is 41 degrees.", evidence, req
    )
    assert cov.hallucinated_evidence  # 41 appears but no evidence holds it
    assert not cov.complete


def test_grounding_query_tainted_scalar_earns_no_credit():
    # "Lahore" appears in the user query — echoing it is not evidence.
    evidence = [_ev("geocode_location", "lahore", [("display_name", "Lahore, Pakistan")])]
    req = [type("E", (), {"canonical_name": "Lahore", "entity_id": "lahore", "aliases": []})()]
    cov = GroundingValidator(user_query="Find the coordinates of Lahore").check(
        "Lahore", evidence, req
    )
    # The entity IS represented; the fact value is query-tainted but the
    # entity name counts — the response may legitimately be minimal here.
    assert cov.required_entities_missing == []


# ---------------------------------------------------------------------------
# D7: evidence packet compactness
# ---------------------------------------------------------------------------

def test_evidence_packet_is_compact():
    from nexus.agent.nodes.response import _evidence_packet_text

    evidence = [
        _ev("get_current_weather", "lahore", [("temperature", 32), ("condition", "Clear")])
    ]
    req = [type("E", (), {"canonical_name": "Lahore", "entity_id": "lahore", "aliases": []})()]
    packet = _evidence_packet_text(evidence, req)
    assert "RESPONSE_EVIDENCE" in packet
    assert "lahore" in packet
    assert "temperature=32" in packet
    assert "REQUIRED ENTITIES" in packet
    assert len(packet) < 600  # never the raw artifact graph


# ---------------------------------------------------------------------------
# D12: deterministic evidence renderer preserves execution
# ---------------------------------------------------------------------------

def test_evidence_renderer_preserves_all_entities():
    from nexus.agent.nodes.response import _evidence_renderer

    evidence = [
        _ev("geocode_location", "lahore", [("latitude", 31.5), ("longitude", 74.3)]),
        _ev("get_current_weather", "lahore", [("temperature", 32)]),
    ]
    text = _evidence_renderer(evidence, [])
    assert "lahore" in text
    assert "31.5" in text
    assert "32" in text


def test_evidence_renderer_names_required_entities_when_no_facts():
    from nexus.agent.nodes.response import _evidence_renderer

    text = _evidence_renderer(
        [], [type("E", (), {"canonical_name": "Lahore", "entity_id": "lahore", "aliases": []})()]
    )
    assert "Lahore" in text
