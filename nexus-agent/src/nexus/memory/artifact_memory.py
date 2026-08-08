"""Artifact Memory — structured execution outputs persisted by content hash.

Additive memory layer (parallel to LLM-extracted semantic memory):
- One entry per artifact: ``artifact_type`` + normalized payload hash +
  ``schema_version`` (the dedup key — identical artifacts from repeated
  cache hits can never duplicate).
- The hash is the artifact's canonical ``content_hash`` (computed on the
  NORMALIZED payload, never raw JSON).
- Zero LLM calls — pure structured persistence (fast, deterministic).
"""

from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger("nexus.memory.artifact_memory")

KIND = "artifact_memory"


async def store_artifact_memory(
    session_id: str | None,
    artifact_type: str,
    tool_name: str,
    schema_version: str,
    content_hash: str,
    payload: dict[str, Any],
) -> bool:
    """Persist one normalized artifact as a memory entry.

    Dedup key = (artifact_type, content_hash, schema_version) — the content
    hash is canonical (normalized payload), so repeated cache hits write
    once. Fire-and-forget semantics: failures never affect execution.

    Args:
        session_id: Optional owning session.
        artifact_type: Artifact discriminator (e.g. ``weather``).
        tool_name: Producing tool.
        schema_version: Artifact schema version (cache-invalidation part).
        content_hash: Canonical hash of the normalized payload.
        payload: The normalized artifact payload (structured memory).

    Returns:
        True when stored (or already present), False on failure.
    """
    try:
        from nexus.memory.store import MemoryStore

        existing = await MemoryStore().find_by_metadata(
            {
                "artifact_type": artifact_type,
                "content_hash": content_hash,
                "schema_version": schema_version,
            },
            kind=KIND,
            top_k=1,
        )
        if existing:
            return True  # dedup: identical normalized artifact already stored

        summary = json.dumps(payload, default=str)
        await MemoryStore().put(
            session_id=session_id,
            kind=KIND,
            content=summary,
            metadata={
                "artifact_type": artifact_type,
                "tool": tool_name,
                "schema_version": schema_version,
                "content_hash": content_hash,
            },
        )
        return True
    except Exception as exc:
        logger.debug("artifact_memory.store_failed", error=str(exc)[:150])
        return False
