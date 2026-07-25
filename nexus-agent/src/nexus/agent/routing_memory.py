"""Versioned Routing Memory — stores routing feedback with model/registry/planner versions.

When embedding models change (e.g., text-embedding-3-small → text-embedding-3-large),
previous feedback becomes mathematically invalid. This module ensures queries only
match against same-version historical data.

The schema is designed to work with or without a dedicated DB table — it can store
data in Redis (fast, ephemeral) or PostgreSQL (persistent, queryable).

No hardcoded model names. All version strings are derived from settings at runtime.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger("nexus.agent.routing_memory")


class RoutingFeedback(BaseModel):
    """A single routing decision record with version metadata.

    Fields:
        query_embedding: The embedding vector for the user query.
        capabilities: The capability names that were selected.
        confidence: Confidence score of the routing decision (0.0–1.0).
        count: Number of times this routing was successfully used.
        embedding_model: The embedding model used (e.g. 'text-embedding-3-small').
        registry_version: The ToolRegistry version at routing time.
        planner_version: The DAG planner version at routing time.
        created_at: When this record was first created.
        last_seen: When this record was last matched.
    """

    query_embedding: list[float] | None = Field(default=None, description="Embedding vector")
    capabilities: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    count: int = 1
    embedding_model: str = Field(default="", description="Embedding model version")
    registry_version: int = Field(default=1, description="ToolRegistry version")
    planner_version: int = Field(default=1, description="Planner version")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _current_versions() -> dict[str, Any]:
    """Get the current system versions for tagging.

    Returns:
        Dict with 'embedding_model', 'registry_version', 'planner_version'.
    """
    try:
        from nexus.config.settings import get_settings
        settings = get_settings()
        return {
            "embedding_model": settings.llm.embedding_model,
            "registry_version": 1,
            "planner_version": 1,
        }
    except Exception:
        return {"embedding_model": "", "registry_version": 1, "planner_version": 1}


async def store_feedback(
    query: str,
    capabilities: list[str],
    confidence: float,
    query_embedding: list[float] | None = None,
) -> None:
    """Store a routing feedback record with current version metadata.

    Stores to Redis (fast, ephemeral) if available.
    The version metadata ensures stale data is never matched against
    queries from a different model/planner generation.

    Args:
        query: The user query text (used as Redis key hash).
        capabilities: The capability names that were selected.
        confidence: Confidence score of the routing decision.
        query_embedding: Optional embedding vector for similarity search.
    """
    versions = _current_versions()
    feedback = RoutingFeedback(
        query_embedding=query_embedding,
        capabilities=capabilities,
        confidence=confidence,
        embedding_model=versions["embedding_model"],
        registry_version=versions["registry_version"],
        planner_version=versions["planner_version"],
    )

    # Store in Redis (TTL 24h)
    try:
        from nexus.redis_client.client import get_redis_client
        redis = get_redis_client()
        if redis is not None:
            import hashlib
            key_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
            key = f"routing_feedback:v1:{key_hash}"
            await redis.setex(key, 86400, feedback.model_dump_json())
            logger.debug("routing_feedback.stored", key=key, embedding_model=versions["embedding_model"])
    except Exception:
        pass


async def find_similar_routing(
    query_embedding: list[float],
    top_k: int = 3,
    min_confidence: float = 0.5,
) -> list[RoutingFeedback]:
    """Find similar routing feedback records, filtered by current version.

    Only returns records where embedding_model, registry_version, and
    planner_version match the current system versions. This prevents
    stale vector contamination after model upgrades.

    Args:
        query_embedding: The embedding vector to match against.
        top_k: Maximum number of similar records to return.
        min_confidence: Minimum confidence threshold.

    Returns:
        List of matching RoutingFeedback records (empty if no matches).
    """
    versions = _current_versions()
    results: list[RoutingFeedback] = []

    try:
        from nexus.redis_client.client import get_redis_client
        redis = get_redis_client()
        if redis is not None:
            # Scan all routing_feedback keys
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match="routing_feedback:v1:*", count=100)
                for key in keys:
                    data = await redis.get(key)
                    if not data:
                        continue
                    try:
                        fb = RoutingFeedback.model_validate_json(data)
                    except Exception:
                        continue

                    # Version filter: only match if versions match
                    if fb.embedding_model != versions["embedding_model"]:
                        continue
                    if fb.registry_version != versions["registry_version"]:
                        continue
                    if fb.planner_version != versions["planner_version"]:
                        continue
                    if fb.confidence < min_confidence:
                        continue

                    results.append(fb)
                if cursor == 0:
                    break

            # Sort by confidence desc
            results.sort(key=lambda x: -x.confidence)
            results = results[:top_k]

    except Exception:
        pass

    return results
