"""Tests for metadata-driven dependency analysis (produces/consumes).

The planner wires upstream/downstream relationships from two signals:
schema field matching (legacy) and the declarative ``produces``/``consumes``
artifact lists (the tool contract's explicit intent).
"""

from __future__ import annotations

from nexus.agent.planners.dependency_analysis import (
    analyze_dependencies,
    build_signatures,
    find_unmet_inputs,
)


def _tool(
    name: str,
    *,
    required: list[str] | None = None,
    outputs: list[str] | None = None,
    produces: list[str] | None = None,
    consumes: list[str] | None = None,
) -> dict:
    return {
        "name": name,
        "input_schema": {
            "type": "object",
            "required": required or [],
            "properties": {k: {"type": "string"} for k in (required or [])},
        },
        "output_schema": {
            "type": "object",
            "properties": {k: {"type": "string"} for k in (outputs or [])},
        },
        "produces": produces or [],
        "consumes": consumes or [],
    }


def test_metadata_produces_consumes_wires_dependency():
    """A tool consuming an artifact another tool produces is a dependency —
    even when schema field names do not match."""
    tools = [
        _tool("geocode", produces=["coordinates"]),
        _tool("weather", consumes=["coordinates"]),
    ]
    deps = analyze_dependencies(tools)
    assert ("geocode", "weather") in deps


def test_schema_dependency_still_detected():
    """Legacy signal keeps working: output field feeds a required input."""
    tools = [
        _tool("a", outputs=["city"]),
        _tool("b", required=["city"]),
    ]
    deps = analyze_dependencies(tools)
    assert ("a", "b") in deps


def test_union_dedupes_overlapping_signals():
    """A pair wired by BOTH signals is emitted exactly once."""
    tools = [
        _tool("a", outputs=["coordinates"], produces=["coordinates"]),
        _tool("b", required=["coordinates"], consumes=["coordinates"]),
    ]
    deps = analyze_dependencies(tools)
    assert deps.count(("a", "b")) == 1


def test_no_dependency_without_shared_contract():
    """Unrelated tools have no edges — metadata and schema both empty."""
    tools = [_tool("a", produces=["x"]), _tool("b", consumes=["y"])]
    assert analyze_dependencies(tools) == []


def test_tool_subset_respected():
    tools = [
        _tool("geocode", produces=["coordinates"]),
        _tool("weather", consumes=["coordinates"]),
        _tool("stocks", consumes=["coordinates"]),
    ]
    deps = analyze_dependencies(tools, tool_subset={"geocode", "stocks"})
    assert ("geocode", "weather") not in deps
    assert ("geocode", "stocks") in deps


def test_signatures_carry_artifacts():
    sig = build_signatures([_tool("t", consumes=["a"], produces=["b"])])
    reqs, outs, consumes, produces = sig["t"]
    assert consumes == {"a"}
    assert produces == {"b"}
    assert reqs == set()
    assert outs == set()


def test_find_unmet_inputs_includes_artifacts():
    """Unmet analysis covers declared artifacts too, not just schema fields."""
    tools = [
        _tool("geocode", produces=["coordinates"]),
        _tool("weather", consumes=["coordinates", "seasons"]),
    ]
    unmet = find_unmet_inputs("weather", tools)
    assert unmet == {"seasons"}
