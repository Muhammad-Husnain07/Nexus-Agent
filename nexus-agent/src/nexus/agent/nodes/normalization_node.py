"""Normalization node — normalizes extracted entity values before merge.

Pure Python, no LLM. Runs all registered normalizers from the
NormalizationRegistry on extracted entities.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.registry.normalization_registry import get_normalization_registry
from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.normalization")


async def normalization_node(state: AgentState) -> dict[str, Any]:
    """Normalize extracted entities before merging into StructuredContext.

    Reads ``_extraction_result``, normalizes all entity values using the
    NormalizationRegistry, and writes back the normalized result.

    Also returns ``_normalization_metadata`` with a record of what was
    resolved (e.g. ``{"resolved_date": "2026-07-25"}``) for the
    context merge node to incorporate into StructuredContext.metadata.

    Pure Python. No LLM. No side effects.
    """
    extraction = state.get("_extraction_result")
    if not extraction:
        return {}

    entities = extraction.get("entities", {})
    if not entities:
        return {}

    registry = get_normalization_registry()
    normalized = registry.normalize_entities(entities)

    # Build metadata from normalizations that changed values
    metadata: dict[str, Any] = {}
    changes = {}
    for k in entities:
        nv = normalized[k]
        if nv != entities[k]:
            changes[k] = {"from": entities[k], "to": nv}
            metadata[f"resolved_{k}"] = nv

    if changes:
        logger.info(
            "normalization_node.applied",
            field_count=len(changes),
            fields=list(changes.keys()),
        )

    return {
        "_extraction_result": {
            **extraction,
            "entities": normalized,
        },
        "_normalization_metadata": metadata if metadata else {},
    }
