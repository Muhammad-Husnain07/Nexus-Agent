"""ArtifactBase — base model for all typed tool outputs.

Every tool execution normalizes its result into an ``ArtifactBase``
subclass.  The ``type`` discriminator enables downstream nodes to
retrieve artifacts by domain without hardcoded field names.

Deep immutability: The ``data`` field is recursively frozen using
``MappingProxyType`` at validation time.  ``artifact_revision``
tracks data changes; ``schema_version`` tracks schema evolution.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Immutable artifact-schema version — part of EVERY cache key that involves
# artifact data (parse/plan/artifact caches). Bump when the artifact payload
# contract changes so stale cached data can never be served.
ARTIFACT_SCHEMA_VERSION = "1.0"


def _deep_freeze(obj: Any) -> Any:
    """Recursively freeze dicts, lists, and sets for deep immutability.

    Scalars (numbers, strings, booleans, None) pass through unchanged.
    (Regression fix: the missing base case previously returned ``None``
    for every scalar — silently nulling all artifact values at the
    freeze step, which produced all-None artifacts across every domain.)
    """
    if isinstance(obj, dict):
        return MappingProxyType({k: _deep_freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(_deep_freeze(v) for v in obj)
    if isinstance(obj, (set, frozenset)):
        return frozenset(_deep_freeze(v) for v in obj)
    return obj


def _canonical(obj: Any) -> Any:
    """Canonicalize frozen payload types (mappingproxy/tuple/frozenset) back
    to plain dict/list/set so JSON serialization is order-independent."""
    if isinstance(obj, MappingProxyType):
        return {k: _canonical(v) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {k: _canonical(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(_canonical(v) for v in obj)
    return obj
    return obj


class ArtifactBase(BaseModel):
    """Typed tool output with traceable provenance and deep immutability.

    Attributes:
        artifact_id: Unique identifier for this artifact.
        execution_id: The execution event that produced this artifact.
        capability_id: The capability that produced this artifact.
        type: Discriminator string (e.g. ``"weather"``, ``"country"``).
        tool_name: Name of the tool that produced this artifact.
        schema_version: Schema version string for cache invalidation.
        artifact_revision: Monotonic revision counter incremented on data changes.
        data: Deeply frozen payload dict.
        created_at: ISO-8601 timestamp.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: UUID = Field(default_factory=uuid4, description="Artifact identifier")
    execution_id: str = Field(default="", description="Execution event UUID")
    capability_id: str = Field(default="", description="Capability identifier")
    type: str = Field(description="Artifact type discriminator")
    tool_name: str = Field(default="", description="Tool that produced this artifact")
    schema_version: str = Field(default="1.0", description="Schema version for cache invalidation")
    artifact_revision: int = Field(default=1, ge=1, description="Monotonic data revision counter")
    content_hash: str = Field(
        default="",
        description="SHA256 of the canonical payload — content-addressable identity for dedup, the artifact cache, and replay",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Deeply frozen payload dict",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 timestamp",
    )

    @model_validator(mode="after")
    def freeze_data(self) -> ArtifactBase:
        """Deep-freeze the data field after validation."""
        object.__setattr__(self, "data", _deep_freeze(self.data))
        if not self.content_hash:
            import hashlib

            canonical = json.dumps(
                _canonical(self.data), sort_keys=True, default=str,
            )
            object.__setattr__(
                self,
                "content_hash",
                hashlib.sha256(canonical.encode()).hexdigest()[:32],
            )
        return self
