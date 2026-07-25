"""StructuredContext — single source of truth for conversation state.

No flags, no booleans. Pure derivable state via EntitySet.
Stores intent, entities, business requirements, metadata, and user decisions.
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
        description="entity_key -> source description (e.g. 'user_turn_3')",
    )
    confidence: dict[str, float] = Field(
        default_factory=dict,
        description="entity_key -> confidence (0.0-1.0)",
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

        Correction: overwrites conflicting fields with new values.
        Additive: only adds fields that don't already exist (preserves existing).
        """
        if is_correction:
            merged_data = {**self.data, **new_data}
            merged_prov = {**self.provenance, **(new_provenance or {})}
            merged_conf = {**self.confidence, **(new_confidence or {})}
        else:
            merged_data = {**new_data, **self.data}
            merged_prov = {**(new_provenance or {}), **self.provenance}
            merged_conf = {**(new_confidence or {}), **self.confidence}

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

    intent: str | list[str] | None = Field(default=None, description="Current user intent(s)")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    entities: EntitySet = Field(default_factory=EntitySet)
    business_requirements: dict[str, Any] = Field(
        default_factory=dict,
        description="Business constraints, filters, thresholds extracted from user request",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Discovered metadata (inferred context, resolved references)",
    )
    user_decisions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Audit trail of user choices and confirmations",
    )
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    def reset_for_new_intent(self, new_intent: str | list[str]) -> StructuredContext:
        """Reset entities when intent changes (detected by extraction)."""
        return StructuredContext(
            intent=new_intent,
            confidence=0.0,
            entities=EntitySet(),
            business_requirements=self.business_requirements.copy(),
            metadata=self.metadata.copy(),
            user_decisions=list(self.user_decisions),
            trace_id=self.trace_id,
        )

    def record_decision(self, field: str, value: Any, reason: str = "") -> StructuredContext:
        """Append a user decision to the audit trail."""
        return self.model_copy(update={
            "user_decisions": self.user_decisions + [{
                "field": field,
                "value": value,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }],
        })

    def set_business_requirement(self, key: str, value: Any) -> StructuredContext:
        """Set a single business requirement."""
        updated = self.business_requirements.copy()
        updated[key] = value
        return self.model_copy(update={"business_requirements": updated})

    def set_metadata(self, key: str, value: Any) -> StructuredContext:
        """Set a single metadata field."""
        updated = self.metadata.copy()
        updated[key] = value
        return self.model_copy(update={"metadata": updated})
