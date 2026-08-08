"""Artifact normalizer — RAW_TOOL_RESULT → NORMALIZED_ARTIFACT (single stage).

Idempotency by design: the normalized payload carries a reserved state
marker (``_nx_state: "normalized"``). Passing an already-normalized payload
back into ``normalize_artifact`` raises ``ArtifactNormalizationError``
immediately — double-normalization is impossible by construction, not by
convention (a flattened payload's declared paths no longer resolve against
raw JSON shapes, which silently produced all-None artifacts).

Also enforces output schemas and applies recursive payload limits so the
ArtifactGraph never holds context-overflowing API payloads.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger("nexus.artifacts.normalizer")

# Bump when the normalized payload contract changes (part of cache keys).
NORMALIZER_VERSION = "2"

# Reserved namespace for normalization state — never present in tool data.
_STATE_KEY = "_nx_state"
_NORMALIZED_STATE = "normalized"
_RESERVED_KEYS = frozenset({"_nx_state", "_nx_normalizer_version"})

MAX_DEPTH = 10
MAX_ITEMS = 20
MAX_STR_LEN = 1000


class ArtifactNormalizationError(Exception):
    """Raised when normalization is invoked on an already-normalized payload
    or a reserved-key payload — the pipeline must never normalize twice."""


class ArtifactContractViolation(Exception):
    """Raised when a declared ``x-artifact-fields`` path fails to resolve.

    A missing extraction must NEVER silently become ``None`` in the artifact
    graph: the registration is aborted and the raw data surfaces explicitly
    instead. Paths declared in the tool's ``x-artifact-optional`` list are
    exempt (legitimately nullable values, e.g. an ongoing manga's chapter
    count)."""


def validate_artifact_contract(
    capability_id: str,
    normalized_data: dict[str, Any],
    flat_fields: dict[str, str],
    optional_fields: set[str] | None = None,
    raw_data: dict[str, Any] | None = None,
) -> None:
    """Validate the normalized payload against the declared flat-field
    contract. Raises ``ArtifactContractViolation`` listing every declared
    path that failed to resolve (absent from the normalized payload).

    Legitimate empty-result exemption: a path whose deepest resolvable
    prefix terminates in an EMPTY collection (e.g. a search with zero
    matches — ``data.Page.media[]`` has no entry at index 0) is a real,
    honest no-match signal, not a normalization failure — the artifact
    registers its projected structure (``media: []``) so the response can
    report the empty result truthfully. A path that fails against MISSING
    structure (an absent key at the first segment) remains a violation.
    """
    optional = optional_fields or set()
    missing = [
        f"{key}@{path}"
        for key, path in flat_fields.items()
        if key not in normalized_data and key not in optional
    ]
    if raw_data:
        missing = [
            item for item in missing
            if not _prefix_is_empty_collection(raw_data, item.split("@", 1)[1])
        ]
    if missing:
        raise ArtifactContractViolation(
            f"{capability_id}: declared artifact fields did not resolve: "
            f"{', '.join(missing)}"
        )


def _prefix_is_empty_collection(raw: dict[str, Any], path: str) -> bool:
    """True when the path's deepest resolvable prefix terminates in an
    empty collection (a no-match structure, not missing data)."""
    current: Any = raw
    for segment in path.split("."):
        idx_match = re.match(r"^([^\[]+)\[(\d+)\]$", segment)
        if idx_match:
            key, idx = idx_match.group(1), int(idx_match.group(2))
            if not (isinstance(current, dict) and key in current):
                return False
            current = current[key]
            if isinstance(current, list):
                if not current or idx >= len(current):
                    return True
                current = current[idx]
            return current is None
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return False
    return False


def _mark(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    payload[_STATE_KEY] = _NORMALIZED_STATE
    payload["_nx_normalizer_version"] = NORMALIZER_VERSION
    return payload


def strip_normalization_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove the reserved normalization keys (for registration/rendering)."""
    return {k: v for k, v in payload.items() if k not in _RESERVED_KEYS}


def is_normalized(payload: dict[str, Any]) -> bool:
    """True when the payload carries the normalization state marker."""
    return isinstance(payload, dict) and payload.get(_STATE_KEY) == _NORMALIZED_STATE


def _limit_payload(obj: Any, depth: int = 0) -> Any:
    """Recursively limit payload size to prevent context overflow.

    Truncates deeply nested structures, large arrays, and long strings
    while preserving the JSON/dict structure for downstream renderers.
    """
    if depth >= MAX_DEPTH:
        return "..."
    if isinstance(obj, dict):
        return {k: _limit_payload(v, depth + 1) for k, v in list(obj.items())[:MAX_ITEMS]}
    if isinstance(obj, list):
        return [_limit_payload(v, depth + 1) for v in obj[:MAX_ITEMS]]
    if isinstance(obj, str):
        return obj[:MAX_STR_LEN] + "..." if len(obj) > MAX_STR_LEN else obj
    return obj


def _deep_extract(obj: Any, path: str) -> Any:
    """Extract a value by a dotted JSON path with array indexes.

    Paths like ``results[0].meanings[0].definitions[0].definition`` resolve
    dictionaries and lists in order. Returns ``None`` on any missing segment
    (never raises).
    """
    current = obj
    for segment in path.split("."):
        if current is None:
            return None
        idx_match = re.match(r"^([^\[]+)\[(\d+)\]$", segment)
        if idx_match:
            key, idx = idx_match.group(1), int(idx_match.group(2))
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
            if isinstance(current, list) and idx < len(current):
                current = current[idx]
            else:
                return None
        elif isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return None
    return current


def normalize_artifact(
    capability_id: str,
    raw_data: dict,
    allowed_fields: set[str] | None = None,
    flat_fields: dict[str, str] | None = None,
) -> dict:
    """Normalize RAW tool result data (single stage of the artifact pipeline).

    Args:
        capability_id: The capability/tool identifier (for logging).
        raw_data: The RAW API response data. Must NOT be an already-normalized
            payload — passing one raises ``ArtifactNormalizationError``.
        allowed_fields: Optional set of field names to project (from
            output_schema). If None, applies ``_limit_payload`` to the whole.
        flat_fields: Optional ``{artifact_key: dotted_json_path}`` map (from
            the output_schema's ``x-artifact-fields`` extension) — deep values
            are promoted to top-level artifact fields.

    Returns:
        The NORMALIZED payload (marked with the normalization state).
        The marker is removed by ``strip_normalization_state`` at registration.

    Raises:
        ArtifactNormalizationError: when ``raw_data`` is already normalized
            (carries the reserved state marker) — double normalization is
            forbidden by design.
    """
    if is_normalized(raw_data):
        raise ArtifactNormalizationError(
            f"normalize_artifact called on an already-normalized payload "
            f"({capability_id}) — double normalization is forbidden"
        )
    if isinstance(raw_data, dict) and (_RESERVED_KEYS & set(raw_data.keys())):
        raise ArtifactNormalizationError(
            f"normalize_artifact received reserved normalization keys "
            f"({capability_id})"
        )
    if flat_fields:
        promoted: dict[str, Any] = {}
        missed: list[str] = []
        for key, path in flat_fields.items():
            value = _deep_extract(raw_data, path)
            if value is not None:
                promoted[key] = value
            else:
                missed.append(f"{key}@{path}")
        if missed:
            logger.debug(
                "normalizer.flatten_misses",
                capability=capability_id,
                paths=missed,
            )
        projected = {
            k: v for k, v in raw_data.items() if k in (allowed_fields or set())
        }
        merged = {**projected, **promoted}
        return _mark(_limit_payload(merged))
    if allowed_fields:
        extracted = {k: v for k, v in raw_data.items() if k in allowed_fields}
        return _mark(_limit_payload(extracted))
    logger.warning("No output_schema for %s. Applying recursive payload limits.", capability_id)
    return _mark(_limit_payload(raw_data))
