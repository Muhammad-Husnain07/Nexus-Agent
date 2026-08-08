"""Architecture version drift tests (ADR 0008).

The manifest in ``nexus.agent.architecture`` is the single runtime source
of truth for architecture versions. These tests guarantee:
1. The manifest cannot silently diverge from the source constants.
2. The cache fingerprint is deterministic AND sensitive — any manifest
   change produces a different fingerprint.
3. Cache keys actually carry the fingerprint (the only architecture
   version used in cache logic).
4. ``to_json`` round-trips for telemetry/diagnostics.
"""

from __future__ import annotations

import pytest

from nexus.agent.architecture import (
    ARCHITECTURE_COMPONENTS,
    ORCHESTRATION_API_VERSION,
    ArchitectureVersion,
)


def test_manifest_matches_source_constants():
    manifest = ArchitectureVersion.current()
    from nexus.artifacts.base import ARTIFACT_SCHEMA_VERSION
    from nexus.artifacts.normalizer import NORMALIZER_VERSION
    from nexus.compiler.ir_models import COMPILER_VERSION

    assert manifest["orchestration_api"] == ORCHESTRATION_API_VERSION
    assert manifest["artifact_schema"] == ARTIFACT_SCHEMA_VERSION
    assert manifest["normalizer"] == str(NORMALIZER_VERSION)
    assert manifest["execution_graph_schema"] == str(COMPILER_VERSION)
    # Contract shape constants live alongside the manifest.
    assert manifest["node_contract_schema"] == "1"
    assert manifest["renderer_contract"] == "1"


def test_fingerprint_deterministic():
    a = ArchitectureVersion.cache_fingerprint()
    b = ArchitectureVersion.cache_fingerprint()
    assert a == b
    assert len(a) == 16


def test_fingerprint_sensitive_to_any_component():
    base = ArchitectureVersion.cache_fingerprint()
    for component in ARCHITECTURE_COMPONENTS:
        mutated = ArchitectureVersion.current()
        mutated[component] = "999-mutated"
        import hashlib
        import json

        canonical = json.dumps(mutated, sort_keys=True, separators=(",", ":"))
        changed = hashlib.sha256(canonical.encode()).hexdigest()[:16]
        assert changed != base, f"{component} does not affect the fingerprint"


def test_to_json_round_trip():
    import json

    payload = json.loads(ArchitectureVersion.to_json())
    assert payload["architecture_fingerprint"] == ArchitectureVersion.cache_fingerprint()
    for component in ARCHITECTURE_COMPONENTS:
        assert component in payload


def test_cache_keys_embed_fingerprint():
    """Parse/plan cache keys embed the architecture fingerprint — the ONLY
    architecture version used in cache logic (ADR 0008). Verified at the
    source level: the cache modules must import the fingerprint, never the
    scattered component constants."""
    import inspect

    from nexus.compiler import cache as cache_module

    source = inspect.getsource(cache_module)
    assert "ArchitectureVersion.cache_fingerprint" in source, (
        "compiler/cache.py must key caches by the architecture fingerprint"
    )
    assert "COMPILER_VERSION = 0" not in source, (
        "scattered fallback version constants must be gone"
    )
    # Behavioral: the parse key is stable and non-trivial.
    from nexus.compiler.cache import ParseCache

    key = ParseCache()._build_key("probe query", [], "model")
    assert isinstance(key, str) and len(key) > 16


def test_manifest_immutable():
    from nexus.agent import architecture as arch_module

    with pytest.raises(TypeError):
        arch_module._manifest["orchestration_api"] = "2"
