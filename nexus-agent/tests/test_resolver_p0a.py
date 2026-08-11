"""P0-A RESOLVER UPGRADE (vNext Phase 1) — semantic ranking + generic
suppression + dependency closure.

The resolver's raw candidates (BM25/alias/NV-embed) are re-ranked
deterministically: specificity lifts specialized capabilities, generic
fallbacks sink and are SUPPRESSED when a specialized candidate clears the
threshold; and the dependency closure adds producers for unsatisfied
REQUIRED inputs so the planner never operates on an incomplete set
(coordinates + weather -> geocode_location is added, no LLM call).
"""

from __future__ import annotations

from nexus.capabilities.capability_semantics import (
    CapabilitySemantics,
    close_dependencies,
    rank_candidates,
)

WEATHER = CapabilitySemantics(
    capability_id="get_current_weather", specificity=0.85,
    consumes=("latitude", "longitude"), produces=("weather_data",),
    requires=("latitude", "longitude"),
)
GEOCODE = CapabilitySemantics(
    capability_id="geocode_location", specificity=0.85,
    consumes=("query",), produces=("location", "coordinates", "latitude", "longitude"),
    requires=("query",),
)
REVERSE = CapabilitySemantics(
    capability_id="reverse_geocode", specificity=0.9,
    consumes=("latitude", "longitude"), produces=("address", "display_name"),
    requires=("latitude", "longitude"),
)
WEB = CapabilitySemantics(
    capability_id="search_web_search", specificity=0.1, generic=True, fallback=True,
    consumes=("q",), produces=("search_results",), requires=("q",),
)
MEALS = CapabilitySemantics(
    capability_id="search_meals", specificity=0.85,
    consumes=("query",), produces=("meal_list",), requires=("query",),
)
SEM = {
    c.capability_id: c for c in (WEATHER, GEOCODE, REVERSE, WEB, MEALS)
}


def test_generic_fallback_suppressed_when_specialized_wins():
    ranked = rank_candidates(
        [("search_meals", 0.6), ("search_web_search", 0.55)], SEM, query="chicken recipes"
    )
    names = [r.name for r in ranked]
    assert "search_meals" in names
    assert "search_web_search" not in names, "generic fallback must be suppressed"
    meals = next(r for r in ranked if r.name == "search_meals")
    assert meals.score > 0.7


def test_generic_kept_when_no_specialized_winner():
    ranked = rank_candidates([("search_web_search", 0.6)], SEM, query="search the web for docker")
    assert [r.name for r in ranked] == ["search_web_search"]


def test_specificity_lifts_specialized_above_generic():
    ranked = rank_candidates(
        [("search_meals", 0.45), ("search_web_search", 0.5)], SEM, query="chicken recipes"
    )
    by_name = {r.name: r for r in ranked}
    assert "search_meals" in by_name
    # the generic is suppressed: a specialized candidate with a genuine
    # retrieval signal (base > 0) beats the alias-driven generic even when
    # the raw scores are scale-incomparable
    assert "search_web_search" not in by_name


def test_explicit_web_request_keeps_generic():
    ranked = rank_candidates(
        [("search_meals", 0.6), ("search_web_search", 0.55)], SEM,
        query="search the web for chicken recipes",
    )
    by_name = {r.name: r for r in ranked}
    assert "search_web_search" in by_name, "explicit web request must keep the generic"
    assert "search_meals" in by_name


def test_evidence_trail_recorded():
    ranked = rank_candidates([("search_meals", 0.6)], SEM, query="chicken recipes")
    r = ranked[0]
    assert "base" in r.evidence
    assert "specialized_bonus" in r.evidence
    assert r.score >= r.evidence["base"]


def test_dependency_closure_adds_producer_for_required_inputs():
    """coordinates + weather: weather requires lat/lon the query cannot
    give; geocode_location produces them -> added deterministically."""
    closed = close_dependencies(
        [("get_current_weather", 0.9)], SEM,
        query_entities={"lahore"},
    )
    names = {n for n, _s in closed}
    assert "get_current_weather" in names
    assert "geocode_location" in names


def test_dependency_closure_no_producer_available():
    closed = close_dependencies(
        [("get_pokemon", 0.9)], SEM, query_entities={"pikachu"}
    )
    assert [n for n, _s in closed] == ["get_pokemon"]


def test_dependency_closure_chain_weather_and_reverse():
    """Both consumers get their lat/lon producer."""
    closed = close_dependencies(
        [("get_current_weather", 0.9), ("reverse_geocode", 0.9)],
        SEM, query_entities={"lahore"},
    )
    names = {n for n, _s in closed}
    assert {"get_current_weather", "reverse_geocode", "geocode_location"} <= names


def test_semantics_derivation_from_registry_shape():
    class _Row:
        name = "get_current_weather"
        validation_rules = {}
        consumes = ["latitude", "longitude"]
        produces = ["weather_data"]
        category = "weather"
        input_schema = {"type": "object", "required": ["latitude", "longitude"],
                        "properties": {}}

    sem = CapabilitySemantics.from_registry("get_current_weather", _Row())
    assert sem.requires == ("latitude", "longitude")
    assert sem.specificity == 0.5  # default when not curated
    assert sem.domains == ("weather",)
