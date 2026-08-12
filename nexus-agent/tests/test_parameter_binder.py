"""P0-B: deterministic parameter + provenance binder tests.

Covers the reviewer's gates:
- B1: weather.latitude/longitude ← geocode outputs (placeholder + dep edge)
- B2: repository user value arrives at the repository-required tool
- B3: multiple entities never reuse one producer's values (identity)
- B4: artifact provenance preserved across parallel A/B pairs
- B5: missing parameter → explicit MissingInput state (not executor failure)
Plus: type-compatibility guard, L5 provenance-checked extraction.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nexus.compiler.binder import (  # noqa: E402
    ParameterBinding,
    _entity_overlap,
    _pick_producer,
    _produced_artifact_names,
    _type_compatible,
    bind_parameters,
)

# Metadata fixture modeled on the live registry (weather/geocode chain).
GC_META = {
    "geocode_location": {
        "input_required": ["query"],
        "input_aliases": {"query": ["location", "city"]},
        "produces": ["location", "coordinates", "latitude", "longitude", "lat", "lon"],
        "consumes": ["query"],
        "input_schema": {"properties": {"query": {"type": "string"}}},
        "output_schema": {"properties": {"latitude": {"type": "number"}, "longitude": {"type": "number"}}},
    },
    "get_current_weather": {
        "input_required": ["latitude", "longitude"],
        "produces": ["weather_data"],
        "consumes": ["latitude", "longitude"],
        "input_schema": {"properties": {
            "latitude": {"type": "number"}, "longitude": {"type": "number"},
        }},
        "output_schema": {"properties": {"temperature": {"type": "number"}}},
    },
    "reverse_geocode": {
        "input_required": ["latitude", "longitude"],
        "produces": ["address", "display_name", "location_details"],
        "consumes": ["latitude", "longitude"],
        "input_schema": {"properties": {
            "latitude": {"type": "number"}, "longitude": {"type": "number"},
        }},
        "output_schema": {"properties": {"address": {"type": "string"}}},
    },
    "get_docker_images": {
        "input_required": ["repository"],
        "produces": ["image_list"],
        "input_schema": {"properties": {
            "namespace": {"type": "string", "default": "library"},
            "repository": {"type": "string"},
        }},
        "output_schema": {"properties": {"name": {"type": "string"}}},
    },
    "search_meals": {
        "input_required": ["query"],
        "produces": ["meal_list"],
        "input_schema": {"properties": {"query": {"type": "string"}}},
    },
    "get_ghibli_films": {
        "input_required": [],
        "produces": ["film_list"],
    },
    "define_word": {
        "input_required": ["word"],
        "produces": ["definition"],
        "input_schema": {"properties": {"word": {"type": "string"}}},
    },
}


@pytest.fixture(autouse=True)
def _fake_gc(monkeypatch):
    import nexus.compiler.binder as binder_mod

    monkeypatch.setattr(
        binder_mod,
        "_meta",
        lambda op: GC_META.get(op, {}),
    )
    yield


# ---------------------------------------------------------------------------
# Gate B1 — coordinates chain binding
# ---------------------------------------------------------------------------

def test_b1_weather_binds_lat_lon_from_geocode():
    nodes = [
        {"op": "geocode_location", "ref": "g1", "inputs": {"query": "Lahore"}, "depends_on": []},
        {"op": "get_current_weather", "ref": "w1", "inputs": {}, "depends_on": []},
    ]
    report = asyncio.run(bind_parameters(nodes, "Find the coordinates of Lahore and tell me the weather there."))
    w1 = nodes[1]
    assert w1["inputs"] == {
        "latitude": "${g1.result.latitude}",
        "longitude": "${g1.result.longitude}",
    }
    assert w1["depends_on"] == ["g1"]
    assert len(report.bindings) == 2
    assert report.missing == []
    sources = {(b.target_parameter, b.source_node, b.source_path) for b in report.bindings}
    assert ("latitude", "g1", "result.latitude") in sources
    assert ("longitude", "g1", "result.longitude") in sources
    assert all(b.source_type == "node_output" for b in report.bindings)


def test_b1_keeps_user_provided_inputs_untouched():
    nodes = [
        {"op": "geocode_location", "ref": "g1", "inputs": {"query": "Lahore"}, "depends_on": []},
        {"op": "get_current_weather", "ref": "w1",
         "inputs": {"latitude": 31.52, "longitude": 74.35}, "depends_on": []},
    ]
    report = asyncio.run(bind_parameters(nodes, "weather Lahore"))
    assert nodes[1]["inputs"] == {"latitude": 31.52, "longitude": 74.35}
    assert report.bindings == []
    assert report.missing == []


# ---------------------------------------------------------------------------
# Gate B2 — repository binding
# ---------------------------------------------------------------------------

def test_b2_user_repository_value_passes_through():
    nodes = [
        {"op": "get_docker_images", "ref": "d1",
         "inputs": {"repository": "facebook/react"}, "depends_on": []},
    ]
    report = asyncio.run(bind_parameters(nodes, "Clone/search issues in facebook/react"))
    assert nodes[0]["inputs"]["repository"] == "facebook/react"
    assert report.missing == []


def test_b2_missing_repository_is_explicit_missing_input():
    nodes = [
        {"op": "get_docker_images", "ref": "d1", "inputs": {}, "depends_on": []},
    ]
    report = asyncio.run(bind_parameters(nodes, "Get repository issues"))
    assert report.bindings == []
    assert len(report.missing) == 1
    m = report.missing[0]
    assert m.parameter == "repository"
    assert m.state == "MISSING"
    assert m.node_id == "d1"
    assert m.clarification_required is True


def test_b2_planner_namespace_guess_dropped_for_schema_default():
    # The planner filled namespace with the repo name; the schema default
    # ("library") must outrank the LLM's guess (the 404 class).
    nodes = [
        {"op": "get_docker_images", "ref": "d1",
         "inputs": {"namespace": "nginx", "repository": "nginx"}, "depends_on": []},
    ]
    asyncio.run(bind_parameters(nodes, "Get information about nginx on Docker Hub"))
    assert nodes[0]["inputs"] == {"repository": "nginx"}  # namespace dropped
    assert nodes[0]["inputs"].get("namespace") is None


# ---------------------------------------------------------------------------
# Gate B3 — entity identity: never reuse one location for both
# ---------------------------------------------------------------------------

def test_b3_two_cities_bind_to_their_own_geocodes():
    nodes = [
        {"op": "geocode_location", "ref": "gLahore", "inputs": {"query": "Lahore"}, "depends_on": []},
        {"op": "geocode_location", "ref": "gIsb", "inputs": {"query": "Islamabad"}, "depends_on": []},
        {"op": "get_current_weather", "ref": "wLahore", "inputs": {}, "depends_on": []},
        {"op": "get_current_weather", "ref": "wIsb", "inputs": {}, "depends_on": []},
    ]
    asyncio.run(bind_parameters(
        nodes, "Get weather in Lahore and Islamabad"))
    # Order of weather nodes is preserved; each binds its OWN producer via
    # deterministic entity overlap (Lahore -> Lahore, Islamabad -> Isb).
    by_ref = {n["ref"]: n for n in nodes}
    assert by_ref["wLahore"]["inputs"]["latitude"] == "${gLahore.result.latitude}"
    assert by_ref["wLahore"]["inputs"]["longitude"] == "${gLahore.result.longitude}"
    assert by_ref["wIsb"]["inputs"]["latitude"] == "${gIsb.result.latitude}"
    assert by_ref["wIsb"]["inputs"]["longitude"] == "${gIsb.result.longitude}"


def test_b3_consumer_with_entity_gets_matching_producer():
    # Consumer carries its own entity -> overlap decides (B3 identity).
    nodes = [
        {"op": "geocode_location", "ref": "g1", "inputs": {"query": "Lahore"}, "depends_on": []},
        {"op": "geocode_location", "ref": "g2", "inputs": {"query": "Tokyo"}, "depends_on": []},
        {"op": "get_current_weather", "ref": "wTokyo", "inputs": {}, "depends_on": []},
    ]
    asyncio.run(bind_parameters(nodes, "weather Tokyo"))
    w = nodes[2]
    assert w["inputs"]["latitude"] == "${g2.result.latitude}"


# ---------------------------------------------------------------------------
# Gate B4 — parallel A/B provenance preserved
# ---------------------------------------------------------------------------

def test_b4_identity_preserved_across_pairs():
    nodes = [
        {"op": "geocode_location", "ref": "gA", "inputs": {"query": "Tokyo"}, "depends_on": []},
        {"op": "geocode_location", "ref": "gB", "inputs": {"query": "Paris"}, "depends_on": []},
        {"op": "get_current_weather", "ref": "wA", "inputs": {}, "depends_on": []},
        {"op": "get_current_weather", "ref": "wB", "inputs": {}, "depends_on": []},
    ]
    asyncio.run(bind_parameters(nodes, "Get weather in Tokyo and Paris"))
    by_ref = {n["ref"]: n for n in nodes}
    assert by_ref["wA"]["inputs"]["latitude"].startswith("${gA.")
    assert by_ref["wB"]["inputs"]["latitude"].startswith("${gB.")


# ---------------------------------------------------------------------------
# Gate B5 — no producer, no user value -> explicit missing state
# ---------------------------------------------------------------------------

def test_b5_no_producer_yields_missing_with_candidate_sources():
    nodes = [
        {"op": "get_current_weather", "ref": "w1", "inputs": {}, "depends_on": []},
    ]
    report = asyncio.run(bind_parameters(nodes, "weather"))
    assert len(report.missing) == 2
    params = {m.parameter for m in report.missing}
    assert params == {"latitude", "longitude"}
    assert all(m.state == "MISSING" for m in report.missing)
    assert all(m.clarification_required for m in report.missing)


# ---------------------------------------------------------------------------
# Type compatibility (L4)
# ---------------------------------------------------------------------------

def test_l4_type_guard_rejects_string_to_number():
    assert not _type_compatible("get_current_weather", "latitude", "reverse_geocode")
    assert _type_compatible("get_current_weather", "latitude", "geocode_location")


def test_l4_unknown_types_trust_semantics():
    # No declared types -> semantic produces list is trusted (never guessed).
    assert _type_compatible("get_docker_images", "repository", "search_meals")


def test_produced_artifact_names_alias_aware():
    # The binder uses the CONSUMER's canonical param name in the placeholder;
    # the executor's field-alias map (latitude->lat) resolves it at runtime.
    assert _produced_artifact_names("geocode_location", "latitude") == ["latitude"]
    assert _produced_artifact_names("get_current_weather", "latitude") == []


# ---------------------------------------------------------------------------
# L5 — provenance-checked LLM extraction fallback
# ---------------------------------------------------------------------------

class _FakeLLM:
    def __init__(self, content: str):
        self._content = content

    async def complete(self, **kwargs):
        return type("R", (), {"failed": False, "content": self._content, "error": None})()


def test_l5_extraction_accepts_only_request_traceable_values():
    nodes = [
        {"op": "get_docker_images", "ref": "d1", "inputs": {}, "depends_on": []},
    ]
    fake = _FakeLLM('{"d1:repository": "facebook/react"}')
    report = asyncio.run(bind_parameters(
        nodes, "Clone/search issues in facebook/react", llm=fake,
        model="fake", allow_llm=True,
    ))
    assert nodes[0]["inputs"].get("repository") == "facebook/react"
    assert report.bindings[0].source_type == "llm"


def test_l5_extraction_rejects_invented_values():
    nodes = [
        {"op": "get_docker_images", "ref": "d1", "inputs": {}, "depends_on": []},
    ]
    fake = _FakeLLM('{"d1:repository": "totally-invented-repo-xyz"}')
    report = asyncio.run(bind_parameters(
        nodes, "Get repository issues", llm=fake, model="fake", allow_llm=True,
    ))
    assert "repository" not in nodes[0].get("inputs", {})
    assert len(report.missing) == 1
    assert report.missing[0].clarification_required is True


def test_l5_not_invoked_when_deterministic_succeeds():
    nodes = [
        {"op": "geocode_location", "ref": "g1", "inputs": {"query": "Lahore"}, "depends_on": []},
        {"op": "get_current_weather", "ref": "w1", "inputs": {}, "depends_on": []},
    ]
    fake = _FakeLLM('{"w1:latitude": "31.5"}')
    report = asyncio.run(bind_parameters(
        nodes, "weather Lahore", llm=fake, model="fake", allow_llm=True,
    ))
    assert report.missing == []
    assert all(b.source_type == "node_output" for b in report.bindings)


# ---------------------------------------------------------------------------
# Sanity: no required inputs -> no bindings, no missing
# ---------------------------------------------------------------------------

def test_no_required_inputs_is_noop():
    nodes = [
        {"op": "get_ghibli_films", "ref": "f1", "inputs": {}, "depends_on": []},
    ]
    report = asyncio.run(bind_parameters(nodes, "List Studio Ghibli films."))
    assert report.bindings == []
    assert report.missing == []
    assert nodes[0]["inputs"] == {}


# ---------------------------------------------------------------------------
# Entity overlap helper
# ---------------------------------------------------------------------------

def test_entity_overlap_scores_shared_values():
    a = {"inputs": {"query": "Lahore"}}
    b = {"inputs": {"query": "Lahore"}}
    c = {"inputs": {"query": "Tokyo"}}
    assert _entity_overlap(a, b) > _entity_overlap(a, c)


def test_pick_producer_prefers_entity_match():
    candidates = [
        {"ref": "g1", "inputs": {"query": "Lahore"}},
        {"ref": "g2", "inputs": {"query": "Tokyo"}},
    ]
    consumer = {"ref": "wTokyo", "inputs": {}}
    picked = _pick_producer(consumer, candidates, "latitude")
    assert picked["ref"] == "g2"


# ---------------------------------------------------------------------------
# AMBIGUOUS state (B3): consumers outnumber distinguishable producers
# ---------------------------------------------------------------------------

def test_ambiguous_when_more_consumers_than_producers():
    # One geocode, two weathers, no entity signals — binding both would
    # silently reuse one location for both (the B3 class). AMBIGUOUS.
    nodes = [
        {"op": "geocode_location", "ref": "g1", "inputs": {"query": "Lahore"}, "depends_on": []},
        {"op": "get_current_weather", "ref": "w1", "inputs": {}, "depends_on": []},
        {"op": "get_current_weather", "ref": "w2", "inputs": {}, "depends_on": []},
    ]
    report = asyncio.run(bind_parameters(nodes, "Get weather."))
    ambiguous = [m for m in report.missing if m.state == "AMBIGUOUS"]
    assert len(ambiguous) == 2  # both latitude AND longitude on the second weather
    assert ambiguous[0].parameter in ("latitude", "longitude")
    assert "geocode_location" in ambiguous[0].candidate_sources
    assert ambiguous[0].clarification_required is True


def test_reuse_legitimate_with_entity_signal():
    # P108 class: "Get the current weather for Lahore twice" — BOTH weathers
    # legitimately reuse the SAME producer (same entity, explicitly twice).
    nodes = [
        {"op": "geocode_location", "ref": "g1", "inputs": {"query": "Lahore"}, "depends_on": []},
        {"op": "get_current_weather", "ref": "w1", "inputs": {}, "depends_on": []},
        {"op": "get_current_weather", "ref": "w2", "inputs": {}, "depends_on": []},
    ]
    report = asyncio.run(bind_parameters(
        nodes, "Get the current weather for Lahore twice"))
    assert len(report.missing) == 0
    assert nodes[1]["inputs"]["latitude"] == "${g1.result.latitude}"
    assert nodes[2]["inputs"]["latitude"] == "${g1.result.latitude}"
