"""Architecture version manifest — the single runtime source of truth.

The orchestration layer is a frozen internal platform. Every architectural
component that affects runtime behavior carries a version here; the
``cache_fingerprint()`` (a SHA256 over the entire manifest) is the ONLY
architecture version used in cache keys, telemetry, diagnostics, and
benchmarks. A breaking change bumps the manifest (policy: ADR 0008),
never individual scattered constants.

Components (frozen contracts):
- orchestration_api: graph topology + routing + state ownership (ADR 0007)
- artifact_schema: the ArtifactBase payload contract (ARTIFACT_SCHEMA_VERSION)
- normalizer: the RAW→NORMALIZED payload contract (NORMALIZER_VERSION)
- node_contract_schema: the node-contract registry shape (contracts.py)
- execution_graph_schema: the ExecutionGraph IR + codegen contract
  (COMPILER_VERSION)
- renderer_contract: the ArtifactRenderer base contract
"""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Any

from nexus.artifacts.base import ARTIFACT_SCHEMA_VERSION
from nexus.artifacts.normalizer import NORMALIZER_VERSION
from nexus.compiler.ir_models import COMPILER_VERSION

# New architecture contracts (frozen by ADR 0008).
ORCHESTRATION_API_VERSION = "1"
NODE_CONTRACT_SCHEMA_VERSION = "1"
RENDERER_CONTRACT_VERSION = "1"

_manifest: MappingProxyType[str, str] = MappingProxyType({
    "orchestration_api": ORCHESTRATION_API_VERSION,
    "artifact_schema": ARTIFACT_SCHEMA_VERSION,
    "normalizer": str(NORMALIZER_VERSION),
    "node_contract_schema": NODE_CONTRACT_SCHEMA_VERSION,
    "execution_graph_schema": str(COMPILER_VERSION),
    "renderer_contract": RENDERER_CONTRACT_VERSION,
})

ARCHITECTURE_COMPONENTS: tuple[str, ...] = tuple(_manifest.keys())


class ArchitectureVersion:
    """Immutable, machine-readable architecture version manifest."""

    @classmethod
    def current(cls) -> dict[str, str]:
        """Deep-copied manifest (runtime/API use)."""
        return dict(_manifest)

    @classmethod
    def cache_fingerprint(cls) -> str:
        """SHA256 over the manifest — the ONLY architecture version in
        cache keys. Changes when any component version changes."""
        canonical = json.dumps(dict(_manifest), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    @classmethod
    def to_json(cls) -> str:
        """Machine-readable manifest with the fingerprint (telemetry,
        diagnostics, CI artifacts)."""
        return json.dumps(
            {**dict(_manifest), "architecture_fingerprint": cls.cache_fingerprint()},
            sort_keys=True,
        )

    @classmethod
    def get(cls, component: str) -> str | None:
        """Version of a single component (None for unknown components)."""
        return _manifest.get(component)
