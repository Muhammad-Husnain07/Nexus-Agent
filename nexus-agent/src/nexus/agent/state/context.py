"""StructuredContext — single source of truth for conversation state.

No flags, no booleans. Pure derivable state via EntitySet.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class EntitySet(BaseModel):
    """Immutable set of extracted entities for the current intent.

    Each entity carries its provenance for debugging and correction handling.
    """

    data: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, str] = Field(
        default_factory=dict,
        description="entity_key → source description (e.g. 'user_turn_3')",
    )
    confidence: dict[str, float] = Field(
        default_factory=dict,
        description="entity_key → confidence (0.0–1.0)",
    )
    version: int = Field(default=0)
    last_updated: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def merge(
        self,
        new_data: dict[str, Any],
        new_provenance: dict[str, str] | None = None,
        new_confidence: dict[str, float] | None = None,
        is_correction: bool = False,
    ) -> EntitySet:
        """Smart merge — replaces on correction, additive otherwise.

        Args:
            new_data: Extracted entities to merge.
            new_provenance: Source tracking per entity.
            new_confidence: Confidence per entity.
            is_correction: If True, overwrites conflicting fields.

        Returns:
            New EntitySet with merged data (immutable).
        """
        if is_correction:
            merged_data = {**self.data, **new_data}
            merged_prov = {**self.provenance, **(new_provenance or {})}
            merged_conf = {**self.confidence, **(new_confidence or {})}
        else:
            merged_data = {**self.data, **new_data}
            merged_prov = {**self.provenance, **(new_provenance or {})}
            merged_conf = {**self.confidence, **(new_confidence or {})}

        return EntitySet(
            data=merged_data,
            provenance=merged_prov,
            confidence=merged_conf,
            version=self.version + 1,
        )


class StructuredContext(BaseModel):
    """Single source of truth — contains ONLY derivable facts.

    No flags like ``is_complete`` or ``missing_fields``.
    Derive everything from ``intent`` + ``entities.data`` at decision time.
    """

    intent: str | None = Field(default=None, description="Current user intent")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    entities: EntitySet = Field(default_factory=EntitySet)
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    def reset_for_new_intent(self, new_intent: str) -> StructuredContext:
        """Reset entities when intent changes (detected by extraction)."""
        return StructuredContext(
            intent=new_intent,
            confidence=0.0,
            entities=EntitySet(),
            trace_id=self.trace_id,
        )
