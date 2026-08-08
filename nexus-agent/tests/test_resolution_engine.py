"""Tests for the ResolutionEngine + ResolutionResult typed contract."""

from __future__ import annotations

import asyncio

import pytest

from nexus.capabilities.resolution_engine import ConfidenceClassifier, ResolutionEngine
from nexus.capabilities.resolution_result import (
    CapabilityCandidate,
    ResolutionResult,
    WorkflowCandidate,
)


class _FakeGC:
    """Minimal GlobalContext stand-in with the metadata the engine reads."""

    def __init__(self) -> None:
        self.capability_index = {
            "get_current_weather": {
                "id": "111", "domain": "weather",
                "aliases": ["get weather"],
                "logical_op_name": "get_current_weather",
                "examples": ["How hot is it right now at latitude 40.71 and longitude -74.00"],
                "keywords": ["weather", "temperature", "latitude", "longitude", "right", "now"],
                "related": ["geocode_location"],
                "cacheable": False,
                "description": "Current weather for coordinates.",
                "search_doc": "get_current_weather weather temperature latitude longitude",
            },
            "geocode_location": {
                "id": "222", "domain": "maps",
                "aliases": ["geocode location"],
                "logical_op_name": "geocode_location",
                "examples": [],
                "keywords": ["weather", "latitude", "longitude", "location", "the", "use", "tool"],
                "related": [],
                "cacheable": True,
                "description": "Coordinates for a place.",
                "search_doc": "geocode_location location latitude longitude maps",
            },
        }
        for i in range(8):
            self.capability_index[f"misc_tool_{i}"] = {
                "id": f"m{i}", "domain": "misc",
                "aliases": [],
                "logical_op_name": f"misc_tool_{i}",
                "examples": [],
                "keywords": ["the", "use", "tool", "user", "for", "and", "whenever", "this"],
                "search_doc": f"misc_tool_{i} the use tool user",
            }
        self.capability_keywords = {k: [k] for k in self.capability_index}
        # Providers with real endpoint URLs — the availability fact requires
        # an executable endpoint (metadata-driven; a provider WITHOUT a URL
        # makes the capability unavailable).
        self.capability_providers = {
            k: [{"url": f"https://example.test/{k}"}] for k in self.capability_index
        }
        self.alias_index = {"get weather": "get_current_weather"}
        self.domain_index = {"weather": ["get_current_weather"], "maps": ["geocode_location"]}
        self.registry_checksum = "abc123"
        self.compiled_graph = None


def _engine() -> ResolutionEngine:
    return ResolutionEngine(top_k=10)


def test_confidence_bands():
    clf = ConfidenceClassifier()
    assert clf.classify(0.95) == "high"
    assert clf.classify(0.80) == "medium"
    assert clf.classify(0.50) == "low"
    # Future multi-factor signature (Phase 6) keeps the same method name.
    assert clf.classify(0.95, {"embedding": 0.4}) == "high"


def test_resolution_result_frozen():
    """The contract is immutable — mutation attempts raise."""
    result = ResolutionResult(
        query="q",
        metadata=__import__(
            "nexus.capabilities.resolution_result", fromlist=["ResolutionMetadata"]
        ).ResolutionMetadata(
            elapsed_ms=1.0, catalog_size=1, fingerprint="f", registry_version=1
        ),
    )
    with pytest.raises(Exception):
        result.query = "other"  # type: ignore[misc]
    with pytest.raises(Exception):
        result.metadata.elapsed_ms = 99.0  # type: ignore[misc]


def test_engine_returns_ranked_candidates_with_sources():
    engine = _engine()
    result = asyncio.run(engine.resolve(
        "How's the weather right now at latitude 31.5 and longitude 74.3?",
        gc=_FakeGC(),
    ))
    assert result.has_capability_candidates is True
    names = [c.name for c in result.capability_candidates]
    assert "get_current_weather" in names
    assert "geocode_location" in names
    # Ranked: the more specific candidate first.
    assert names[0] == "get_current_weather"
    top = result.capability_candidates[0]
    assert top.id == "111"
    assert top.score > 0
    assert top.confidence in ("high", "medium", "low")
    assert top.match_sources, "multi-source reasons must be populated"
    assert top.availability == "available"


def test_engine_excludes_unavailable_via_domain():
    """Domain narrowing is metadata-driven; unrelated domains are excluded."""
    engine = _engine()
    result = asyncio.run(engine.resolve(
        "How's the weather?",
        domain_hint="weather",
        gc=_FakeGC(),
    ))
    names = [c.name for c in result.capability_candidates]
    assert all("geocode_location" not in n for n in names)
    assert "get_current_weather" in names


def test_engine_binary_facts_no_workflow_without_templates():
    engine = _engine()
    result = asyncio.run(engine.resolve("weather please", gc=_FakeGC()))
    assert result.has_workflow_candidates is False
    assert result.workflow_candidates == ()


def test_engine_metadata_typed():
    engine = _engine()
    result = asyncio.run(engine.resolve("weather please", gc=_FakeGC()))
    assert result.metadata.catalog_size == len(_FakeGC().capability_index)
    assert result.metadata.layers_run
    assert result.metadata.resolver_version >= 1
    assert result.explanation, "explanation is populated for debug/telemetry"


def test_engine_generic_query_does_not_boost_misc():
    """Prose-only keywords must not boost misc capabilities."""
    engine = _engine()
    result = asyncio.run(engine.resolve("the user wants to use this tool", gc=_FakeGC()))
    names = [c.name for c in result.capability_candidates]
    assert not any(n.startswith("misc_tool_") for n in names)


def test_candidate_base_shapes_future_executables():
    """CapabilityCandidate and WorkflowCandidate share CandidateBase — the
    Phase 9 unified executable space needs no model surgery."""
    cap = CapabilityCandidate(id="1", name="a", score=0.9, confidence="high")
    wf = WorkflowCandidate(id="2", name="b", score=0.8, confidence="medium")
    assert cap.name and wf.name
    assert {f.name for f in (cap, wf)} == {"a", "b"}
