"""Immutable Context Intermediate Representation for prompt compilation.

The ``ContextIR`` is the compiled target of the prompt pipeline — it holds
selected, deduplicated, and compressed context items ready for rendering.
Each item carries a ``PromptProjection`` with revisioned artifact data.

No hardcoded field names or model-specific logic. All types are enums
or data classes with frozen=True for immutability.
"""

from __future__ import annotations

import copy
import enum
import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Optional

# Shared constant for token-aware compression — centralized to avoid duplication
VERBOSE_FIELDS = frozenset({"description", "summary", "narrative", "content", "text"})


def _deep_unfreeze(obj: Any) -> Any:
    """Recursively convert MappingProxyType/tuple back to plain dict/list for JSON serialization."""
    if isinstance(obj, MappingProxyType):
        return {k: _deep_unfreeze(v) for k, v in obj.items()}
    if isinstance(obj, tuple):
        return [_deep_unfreeze(v) for v in obj]
    return obj


class ContextSection(enum.Enum):
    """Semantic sections of a compiled prompt."""
    SYSTEM_INSTRUCTIONS = "system_instructions"
    USER_INTENT = "user_intent"
    ARTIFACTS = "artifacts"
    HISTORY = "history"


class Priority(enum.IntEnum):
    """Sort priority for context items (higher = more important)."""
    SYSTEM = 100
    CURRENT_USER = 95
    ARTIFACT = 80
    RECENT_HISTORY = 60
    OLD_HISTORY = 20


@dataclass(frozen=True)
class PromptProjection:
    """A frozen projection of an artifact into the prompt context.

    Attributes:
        artifact_id: Unique artifact identifier.
        capability_id: The capability that produced this artifact.
        artifact_type: Type discriminator string.
        schema_version: Schema version for cache invalidation.
        artifact_revision: Monotonic revision counter for data changes.
        data: Deeply frozen artifact data dict.
    """
    artifact_id: str
    capability_id: str
    artifact_type: str
    schema_version: str
    artifact_revision: int
    data: dict[str, Any]

    @classmethod
    def from_artifact(cls, artifact: Any) -> PromptProjection:
        """Build a PromptProjection from an ArtifactBase, unfreezing its data."""
        raw = artifact.data
        # Deep unfreeze to ensure standard dicts for JSON serialization
        if isinstance(raw, MappingProxyType):
            unfrozen = _deep_unfreeze(raw)
        elif isinstance(raw, dict):
            unfrozen = _deep_unfreeze(raw)  # Still deep unfreeze in case of nested proxies
        else:
            unfrozen = {}
            
        return cls(
            artifact_id=str(artifact.artifact_id),
            capability_id=getattr(artifact, "capability_id", "") or getattr(artifact, "tool_name", ""),
            artifact_type=getattr(artifact, "type", "unknown"),
            schema_version=getattr(artifact, "schema_version", "1.0"),
            artifact_revision=getattr(artifact, "artifact_revision", 1),
            data=unfrozen,
        )


@dataclass(frozen=True)
class ContextItem:
    """A single item in the context IR.

    Attributes:
        section: Which semantic section this item belongs to.
        speaker: Role string (e.g. 'user', 'assistant', 'system').
        projection: Optional artifact projection (for ARTIFACTS section).
        content: Optional text content (for non-artifact items).
        priority: Sort priority from the Priority enum.
    """
    section: ContextSection
    speaker: str
    projection: Optional[PromptProjection] = None
    content: Optional[str] = None
    priority: int = Priority.OLD_HISTORY


@dataclass(frozen=True)
class ContextPolicy:
    """Policy for selecting and pruning context items.

    Attributes:
        purpose: Human-readable purpose string for cache key.
        max_history_turns: Max conversation turns to include.
        max_artifacts: Max artifact projections to include.
    """
    purpose: str
    max_history_turns: int = 5
    max_artifacts: int = 8


@dataclass(frozen=True)
class ContextIR:
    """Immutable compiled context ready for rendering.

    Attributes:
        items: Ordered tuple of context items (sorted, selected, compressed).
        schema_versions: Mapping of capability_id → schema_version for cache.
        budget_limit: Token budget for the compiled prompt.
        model_name: Target model identifier.
        policy: Selection/pruning policy used during compilation.
        context_id: Unique identifier for this compiled context.
    """
    items: tuple[ContextItem, ...] = ()
    schema_versions: dict[str, str] = field(default_factory=dict)
    budget_limit: int = 0
    model_name: str = ""
    policy: ContextPolicy = field(default_factory=lambda: ContextPolicy(purpose="compiled"))
    context_id: str = ""

    def fingerprint(self, renderer_version_hash: str) -> str:
        """Compute a deterministic cache key for this compiled context.

        Includes policy, model, schema versions, and item content hashes.
        Two ContextIRs with the same fingerprint produce identical rendered prompts.
        """
        policy_str = (
            f"{self.policy.purpose}|{self.policy.max_history_turns}|{self.policy.max_artifacts}"
        )
        version_str = (
            f"2.0|{renderer_version_hash}|{self.model_name}|{policy_str}|"
            f"{json.dumps(self.schema_versions, sort_keys=True)}"
        )
        sorted_items = sorted(
            self.items, key=lambda x: (x.section.value, x.priority, x.speaker)
        )

        def get_item_id(i: ContextItem) -> str:
            if i.projection:
                return (
                    f"art:{i.projection.artifact_id}:"
                    f"v{i.projection.schema_version}:r{i.projection.artifact_revision}"
                )
            return f"text:{hashlib.sha256((i.content or '').encode()).hexdigest()[:8]}"

        id_str = "|".join([get_item_id(i) for i in sorted_items])
        return hashlib.sha256(f"{version_str}|{id_str}".encode()).hexdigest()[:16]
