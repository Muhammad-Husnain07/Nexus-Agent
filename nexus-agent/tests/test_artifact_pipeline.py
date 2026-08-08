"""Artifact pipeline regression tests — Steps 1–5 guardrails.

1. Normalization idempotency: normalize_artifact raises on an already-
   normalized payload (double normalization is impossible by design).
2. Contract validation: a declared x-artifact-fields path that fails to
   resolve is a violation (never a silent None); x-artifact-optional paths
   are exempt.
3. Flatten completeness: for every registered tool contract with declared
   x-artifact-fields, a representative RAW sample must resolve every
   declared path to a non-None value.
4. Provenance: registered artifacts carry execution_id, tool_name,
   schema_version, and the normalized payload records the normalizer
   version.
"""

from __future__ import annotations

import pytest

from nexus.artifacts.normalizer import (
    ArtifactContractViolation,
    ArtifactNormalizationError,
    is_normalized,
    normalize_artifact,
    strip_normalization_state,
    validate_artifact_contract,
)

WEATHER_RAW = {
    "latitude": 35.7,
    "longitude": 139.6875,
    "current_weather": {
        "temperature": 29.5,
        "windspeed": 4.5,
        "winddirection": 151,
        "weathercode": 0,
        "time": "2026-08-07T00:45",
        "is_day": 1,
    },
}
WEATHER_FLAT = {
    "latitude": "latitude",
    "longitude": "longitude",
    "temperature_c": "current_weather.temperature",
    "windspeed_kmh": "current_weather.windspeed",
    "weathercode": "current_weather.weathercode",
    "recorded_at": "current_weather.time",
}


def test_normalization_is_idempotent_by_design():
    normalized = normalize_artifact("w", WEATHER_RAW, flat_fields=WEATHER_FLAT)
    assert is_normalized(normalized)
    assert normalized["_nx_state"] == "normalized"
    with pytest.raises(ArtifactNormalizationError):
        normalize_artifact("w", normalized, flat_fields=WEATHER_FLAT)
    with pytest.raises(ArtifactNormalizationError):
        normalize_artifact("w", {"_nx_state": "normalized", "x": 1})


def test_strip_removes_markers_only():
    normalized = normalize_artifact("w", WEATHER_RAW, flat_fields=WEATHER_FLAT)
    stripped = strip_normalization_state(normalized)
    assert "_nx_state" not in stripped
    assert "_nx_normalizer_version" not in stripped
    assert stripped["temperature_c"] == 29.5


def test_flatten_resolves_declared_paths():
    normalized = normalize_artifact("w", WEATHER_RAW, flat_fields=WEATHER_FLAT)
    stripped = strip_normalization_state(normalized)
    for key in WEATHER_FLAT:
        assert stripped.get(key) is not None, f"{key} failed to resolve"


def test_contract_violation_on_missing_path():
    raw = {"latitude": 35.7, "longitude": 139.6875}  # no current_weather
    normalized = normalize_artifact("w", raw, flat_fields=WEATHER_FLAT)
    stripped = strip_normalization_state(normalized)
    with pytest.raises(ArtifactContractViolation):
        validate_artifact_contract("w", stripped, WEATHER_FLAT)
    # optional exemption: every missing path declared optional passes
    validate_artifact_contract(
        "w", stripped, WEATHER_FLAT,
        {"temperature_c", "windspeed_kmh", "weathercode", "recorded_at"},
    )


def test_optional_fields_exempt():
    manga_flat = {"title": "data.Page.media[0].title.romaji",
                  "chapters": "data.Page.media[0].chapters"}
    raw = {"data": {"Page": {"media": [{"title": {"romaji": "ONE PIECE"}, "chapters": None}]}}}
    normalized = strip_normalization_state(normalize_artifact("m", raw, flat_fields=manga_flat))
    # chapters=None is NOT promoted (normalizer skips None) → optional exempts it
    validate_artifact_contract("m", normalized, manga_flat, {"chapters"})
    with pytest.raises(ArtifactContractViolation):
        validate_artifact_contract("m", normalized, manga_flat)


def test_empty_results_exempted_not_missing_data():
    """A no-match search (empty media list) is a legitimate artifact — its
    declared paths fail into an empty collection, not missing structure."""
    manga_flat = {"title": "data.Page.media[0].title.romaji"}
    no_match = {"data": {"Page": {"media": []}}}
    normalized = strip_normalization_state(
        normalize_artifact("m", no_match, flat_fields=manga_flat)
    )
    # Exempt with the raw (empty prefix) — the honest no-match registers.
    validate_artifact_contract(
        "m", normalized, manga_flat, raw_data=no_match,
    )
    # WITHOUT the raw context the empty payload still violates (no data).
    with pytest.raises(ArtifactContractViolation):
        validate_artifact_contract("m", normalized, manga_flat)
    # MISSING structure (the API shape absent) is still a hard violation.
    malformed = {"error": "boom"}
    with pytest.raises(ArtifactContractViolation):
        validate_artifact_contract(
            "m", {}, manga_flat, raw_data=malformed,
        )


def test_provenance_fields_present():
    from nexus.artifacts.base import ArtifactBase

    artifact = ArtifactBase(
        capability_id="w", type="weather", tool_name="get_current_weather",
        data={"temperature_c": 29.5}, execution_id="exec-1",
    )
    assert artifact.execution_id == "exec-1"
    assert artifact.tool_name == "get_current_weather"
    assert artifact.schema_version == "1.0"
    assert artifact.content_hash, "content_hash must be computed at validation"
    assert artifact.created_at


def test_deep_freeze_preserves_scalar_values():
    """Regression: the freeze step must never null scalar values.

    The missing base case in ``_deep_freeze`` returned ``None`` for every
    scalar — silently producing all-None artifacts across every domain
    (the every-query-fails root cause).
    """
    from nexus.artifacts.base import ArtifactBase

    artifact = ArtifactBase(
        type="weather", tool_name="get_current_weather",
        data={
            "latitude": 35.7,
            "longitude": 139.6875,
            "current_weather": {
                "temperature": 29.5,
                "windspeed": 8.0,
                "is_day": 1,
                "weathercode": 0,
                "recorded_at": "2026-08-07T08:00",
            },
        },
        execution_id="exec-2",
    )
    assert dict(artifact.data)["latitude"] == 35.7
    assert dict(artifact.data)["longitude"] == 139.6875
    nested = dict(dict(artifact.data)["current_weather"])
    assert nested["temperature"] == 29.5
    assert nested["windspeed"] == 8.0
    assert nested["is_day"] == 1
    assert nested["weathercode"] == 0
    assert nested["recorded_at"] == "2026-08-07T08:00"
    # content_hash must be computed from the REAL payload (not the nulled one)
    assert artifact.content_hash != ArtifactBase(
        type="weather", tool_name="get_current_weather",
        data={"latitude": None, "current_weather": {"temperature": None}},
        execution_id="exec-2b",
    ).content_hash
