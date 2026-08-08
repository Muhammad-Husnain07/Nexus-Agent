"""Tests for dynamic metadata-driven input/op normalization.

Covers:
- ``_sanitize_ops`` — layered resolution (exact → domain → alias → fuzzy)
  with unresolved ops collected for LLM repair (never guessed below threshold)
- ``_coerce_inputs_to_schema`` — schema x-aliases first, then fuzzy remap
- ``fuzzy_best_match`` / ``resolve_operation`` — shared RapidFuzz core
"""

from __future__ import annotations

from nexus.agent.nodes.semantic_parser_node import _extract_returns, _sanitize_ops
from nexus.capabilities.resolution import fuzzy_best_match, resolve_operation
from nexus.tools.executor import (
    _apply_schema_defaults,
    _coerce_inputs_to_schema,
    _output_validation_error,
)

# ---------------------------------------------------------------------------
# Layered op sanitization
# ---------------------------------------------------------------------------


def test_sanitize_keeps_exact_matches():
    out = _sanitize_ops([{"op": "get_invoice"}], ["get_invoice", "pokeapi_get_pokemon"])
    assert [n["op"] for n in out] == ["get_invoice"]
    assert "_unresolved_ops" not in out[0]


def test_sanitize_remaps_near_exact_op():
    """getinvoice is ≥95 similar to get_invoice → auto-remapped."""
    out = _sanitize_ops([{"op": "getinvoice"}], ["get_invoice"])
    assert out[0]["op"] == "get_invoice"


def test_sanitize_collects_unresolved_for_repair():
    """Below-threshold ops are kept with _unresolved_ops (LLM repair path)."""
    out = _sanitize_ops([{"op": "GetPokemonInformation"}], ["pokeapi_get_pokemon"])
    assert out[0]["op"] == "GetPokemonInformation"
    assert "_unresolved_ops" in out[0]
    assert out[0]["_unresolved_ops"] == ["GetPokemonInformation"]


def test_sanitize_handles_empty_catalog():
    out = _sanitize_ops([{"op": "whatever"}], [])
    assert len(out) == 1


# ---------------------------------------------------------------------------
# Shared fuzzy core (capabilities/resolution.py)
# ---------------------------------------------------------------------------


def test_fuzzy_best_match_above_threshold():
    best = fuzzy_best_match("getinvoice", ["get_invoice", "pokeapi_get_pokemon"])
    assert best is not None
    assert best[0] == "get_invoice"


def test_fuzzy_best_match_below_threshold_is_none():
    """Never guess below the threshold — None means escalate to repair."""
    best = fuzzy_best_match("GetPokemonInformation", ["pokeapi_get_pokemon"])
    assert best is None


def test_fuzzy_best_match_threshold_override():
    best = fuzzy_best_match("getpokemon", ["pokeapi_get_pokemon"], threshold=80.0)
    assert best is not None
    assert best[0] == "pokeapi_get_pokemon"


def test_resolve_operation_exact_layer():
    r = resolve_operation("get_invoice", catalog=["get_invoice"])
    assert r.op == "get_invoice"
    assert r.layer == "exact"
    assert r.confidence == 100.0


def test_resolve_operation_alias_layer():
    r = resolve_operation(
        "pokemon info",
        alias_index={"pokemon info": "pokeapi_get_pokemon"},
        catalog=["pokeapi_get_pokemon"],
    )
    assert r.op == "pokeapi_get_pokemon"
    assert r.layer == "alias"
    assert r.confidence == 100.0


def test_resolve_operation_domain_narrowing():
    """An op inside the domain-scoped set (but not a global exact) resolves
    at the domain layer — the domain index IS the catalog for that domain."""
    r = resolve_operation(
        "pokeapi_get_pokemon",
        domain_index={"pokemon": ["pokeapi_get_pokemon", "pokeapi_get_species"]},
        domain_hint="pokemon",
        catalog=["get_weather"],
    )
    assert r.op == "pokeapi_get_pokemon"
    assert r.layer == "domain"


def test_resolve_operation_below_threshold_escalates():
    """Below-threshold op in the domain never auto-resolves — repair path."""
    r = resolve_operation(
        "get_pokemon",
        domain_index={"pokemon": ["pokeapi_get_pokemon", "pokeapi_get_species"]},
        domain_hint="pokemon",
        catalog=["pokeapi_get_pokemon", "pokeapi_get_species"],
    )
    assert r.op is None
    assert r.layer == "failed"


def test_resolve_operation_failed_layer():
    r = resolve_operation("totally_made_up_thing", catalog=["pokeapi_get_pokemon"])
    assert r.op is None
    assert r.layer == "failed"


# ---------------------------------------------------------------------------
# Input coercion (x-aliases first, then fuzzy)
# ---------------------------------------------------------------------------


def test_coerce_uses_declared_x_aliases():
    schema = {
        "type": "object",
        "properties": {
            "pokemon_name": {
                "type": "string",
                "x-aliases": ["pokemon", "name", "pokemonName"],
            }
        },
    }
    out = _coerce_inputs_to_schema({"pokemon": "pikachu"}, schema)
    assert out == {"pokemon_name": "pikachu"}


def test_coerce_fuzzy_remap_when_no_alias():
    schema = {
        "type": "object",
        "properties": {"pokemon_name": {"type": "string"}},
    }
    out = _coerce_inputs_to_schema({"pokemonname": "pikachu"}, schema)
    assert out == {"pokemon_name": "pikachu"}


def test_coerce_stringifies_scalar():
    schema = {
        "type": "object",
        "properties": {"pokemon_name": {"type": "string"}},
    }
    out = _coerce_inputs_to_schema({"pokemon_name": True}, schema)
    assert out == {"pokemon_name": "true"}


def test_coerce_numeric_string_to_number():
    schema = {
        "type": "object",
        "properties": {
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
        },
    }
    out = _coerce_inputs_to_schema({"latitude": 31.5204, "longitude": "74.3587"}, schema)
    assert out == {"latitude": 31.5204, "longitude": 74.3587}
    assert isinstance(out["longitude"], float)


def test_coerce_numeric_string_to_integer():
    schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
    out = _coerce_inputs_to_schema({"count": "7"}, schema)
    assert out == {"count": 7}
    assert isinstance(out["count"], int)


def test_coerce_integral_float_to_integer():
    schema = {"type": "object", "properties": {"page": {"type": "integer"}}}
    out = _coerce_inputs_to_schema({"page": 2.0}, schema)
    assert out == {"page": 2}


def test_coerce_ignores_non_numeric_string():
    schema = {"type": "object", "properties": {"latitude": {"type": "number"}}}
    assert _coerce_inputs_to_schema({"latitude": "not-a-number"}, schema) is None


def test_coerce_noop_on_exact_inputs():
    schema = {
        "type": "object",
        "properties": {"pokemon_name": {"type": "string"}},
    }
    assert _coerce_inputs_to_schema({"pokemon_name": "pikachu"}, schema) is None


def test_coerce_unrelated_keys_untouched():
    schema = {
        "type": "object",
        "properties": {"pokemon_name": {"type": "string"}},
    }
    assert _coerce_inputs_to_schema({"zzz": "x"}, schema) is None


def test_defaults_fill_missing_optional_params():
    schema = {
        "type": "object",
        "required": ["latitude", "longitude"],
        "properties": {
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
            "current_weather": {"type": "boolean", "default": True},
        },
    }
    out = _apply_schema_defaults({"latitude": 31.5, "longitude": 74.3}, schema)
    assert out == {"latitude": 31.5, "longitude": 74.3, "current_weather": True}


def test_defaults_preserve_provided_values():
    schema = {
        "type": "object",
        "properties": {"current_weather": {"type": "boolean", "default": True}},
    }
    out = _apply_schema_defaults({"current_weather": False}, schema)
    assert out == {"current_weather": False}


def test_defaults_skip_no_default_and_null_default():
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "string", "default": None},
        },
    }
    assert _apply_schema_defaults({}, schema) == {}


def test_extract_returns_handles_missing_outputs():
    """A capability without declared output properties must yield an empty
    list — this used to crash the whole catalog build ('list' object has no
    attribute 'keys') and starve the planner prompt of every description."""
    from nexus.agent.nodes.semantic_parser_node import _extract_returns

    outputs = {"get_current_weather": {"latitude": {}, "longitude": {}}}
    assert _extract_returns(outputs, "get_current_weather", "get_current_weather") == [
        "latitude",
        "longitude",
    ]
    assert _extract_returns(outputs, "geocode_location", "geocode_location") == []
    assert _extract_returns(outputs, "missing", "also_missing") == []
    assert _extract_returns({}, "any", "any") == []


def test_output_validation_unwraps_wrapped_array():
    """The executor wraps top-level array responses as {"results": [...]} —
    a schema declaring ``type: array`` must validate against the unwrapped
    list (geocode-style tools return array payloads)."""
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["place_id", "lat", "lon"],
            "properties": {
                "place_id": {"type": "integer"},
                "lat": {"type": "string"},
                "lon": {"type": "string"},
            },
        },
    }
    wrapped = {"results": [{"place_id": 1, "lat": "31.5", "lon": "74.3"}]}
    assert _output_validation_error(wrapped, schema) is None

    bad = {"results": [{"place_id": 1}]}
    assert _output_validation_error(bad, schema) is not None

    # Non-array schemas validate the wrapper dict as-is.
    obj_schema = {"type": "object", "required": ["results"]}
    assert _output_validation_error(wrapped, obj_schema) is None
