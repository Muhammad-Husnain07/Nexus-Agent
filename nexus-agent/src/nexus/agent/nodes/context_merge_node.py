"""Context Merge node — merges extraction result into StructuredContext.

Pure Python. No LLM. Handles intent changes, entity corrections,
business requirements, and normalization metadata.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.state import AgentState
from nexus.agent.state.context import EntitySet, StructuredContext

logger = structlog.get_logger("nexus.agent.nodes.context_merge")


def _extract_provenance(state: AgentState) -> str:
    """Derive a provenance string from the current state."""
    messages = state.get("messages", [])
    return f"user_turn_{len(messages)}"


def _merge_business_requirements(
    current: dict[str, Any],
    new: dict[str, Any],
    is_correction: bool,
) -> dict[str, Any]:
    """Merge business requirements — correction overwrites, additive preserves."""
    if is_correction:
        return {**current, **new}
    return {**new, **current}


def _merge_metadata(
    current: dict[str, Any],
    new: dict[str, Any],
) -> dict[str, Any]:
    """Merge normalization metadata — new values always win (fresh resolutions)."""
    if not new:
        return current
    return {**current, **new}


async def context_merge_node(state: AgentState) -> dict[str, Any]:
    """Merge extraction result into StructuredContext.

    Determines if this is a:
    - New intent (reset context)
    - Correction (merge with overwrite)
    - Continuation (additive merge)

    Also merges business_requirements and normalization metadata.
    Returns updated StructuredContext. No flags.
    """
    extraction = state.get("_extraction_result")
    current_ctx: StructuredContext | None = state.get("_structured_context")
    provenance = _extract_provenance(state)
    normalization_metadata = state.get("_normalization_metadata", {}) or {}

    if not extraction:
        return {}

    intent = extraction.get("intent")
    entities = extraction.get("entities", {})
    business_requirements = extraction.get("business_requirements", {}) or {}
    confidence = float(extraction.get("confidence", 0.0))
    entity_conf = extraction.get("entity_confidence", {})

    # If we have normalization metadata, merge it into the extracted entities
    # so that normalized values are used (the extraction already has them from
    # the normalization node, but metadata gives us context about what changed)
    metadata_updates = {**normalization_metadata}

    # First extraction — create fresh context
    if not current_ctx or current_ctx.intent is None:
        ctx = StructuredContext(
            intent=intent,
            confidence=confidence,
            entities=EntitySet(
                data=entities,
                provenance={k: provenance for k in entities},
                confidence={k: entity_conf.get(k, confidence) for k in entities},
            ),
            business_requirements=business_requirements,
            metadata=metadata_updates,
        )
        logger.info("context_merge.new_context", intent=intent, confidence=confidence)
        return {"_structured_context": ctx}

    # Intent changed — reset
    if intent != current_ctx.intent:
        new_ctx = current_ctx.reset_for_new_intent(intent)
        new_ctx.confidence = confidence
        new_ctx.entities = EntitySet(
            data=entities,
            provenance={k: provenance for k in entities},
            confidence={k: entity_conf.get(k, confidence) for k in entities},
        )
        new_ctx = new_ctx.set_business_requirement("_just_changed", True)
        logger.info("context_merge.intent_changed", old=current_ctx.intent, new=intent)
        return {"_structured_context": new_ctx}

    # Same intent — merge entities (additive)
    is_correction = any(k in current_ctx.entities.data for k in entities)

    merged_entities = current_ctx.entities.merge(
        new_data=entities,
        new_provenance={k: provenance for k in entities},
        new_confidence={k: entity_conf.get(k, confidence) for k in entities},
        is_correction=is_correction,
    )

    merged_business = _merge_business_requirements(
        current_ctx.business_requirements,
        business_requirements,
        is_correction,
    )

    merged_metadata = _merge_metadata(
        current_ctx.metadata,
        metadata_updates,
    )

    ctx = current_ctx.model_copy(update={
        "confidence": max(current_ctx.confidence, confidence),
        "entities": merged_entities,
        "business_requirements": merged_business,
        "metadata": merged_metadata,
    })

    logger.info(
        "context_merge.merged",
        version=merged_entities.version,
        correction=is_correction,
        entity_count=len(merged_entities.data),
        business_req_count=len(merged_business),
        metadata_count=len(merged_metadata),
    )

    return {"_structured_context": ctx}
