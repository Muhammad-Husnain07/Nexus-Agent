"""Context Merge node — merges extraction result into StructuredContext.

Pure Python. No LLM. Handles intent changes and entity corrections.
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


async def context_merge_node(state: AgentState) -> dict[str, Any]:
    """Merge extraction result into StructuredContext.

    Determines if this is a:
    - New intent (reset context)
    - Correction (merge with overwrite)
    - Continuation (additive merge)

    Returns updated StructuredContext. No flags.
    """
    extraction = state.get("_extraction_result")
    current_ctx: StructuredContext | None = state.get("_structured_context")
    provenance = _extract_provenance(state)

    if not extraction:
        return {}

    intent = extraction.get("intent")
    entities = extraction.get("entities", {})
    confidence = float(extraction.get("confidence", 0.0))
    entity_conf = extraction.get("entity_confidence", {})

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
        logger.info("context_merge.intent_changed", old=current_ctx.intent, new=intent)
        return {"_structured_context": new_ctx}

    # Same intent — merge entities (additive)
    # Correction detection: if user provides a value for an already-extracted
    # field, it's a correction (the merge with overwrite handles this)
    is_correction = any(k in current_ctx.entities.data for k in entities)

    merged = current_ctx.entities.merge(
        new_data=entities,
        new_provenance={k: provenance for k in entities},
        new_confidence={k: entity_conf.get(k, confidence) for k in entities},
        is_correction=is_correction,
    )

    ctx = current_ctx.model_copy(update={
        "confidence": max(current_ctx.confidence, confidence),
        "entities": merged,
    })

    logger.info(
        "context_merge.merged",
        version=merged.version,
        correction=is_correction,
        entity_count=len(merged.data),
    )

    return {"_structured_context": ctx}
