"""MemoryConsolidator — background job for memory maintenance.

Runs the full consolidation pipeline:
1. Cluster similar memories via embedding + DBSCAN, merge via LLM
2. Promote high-importance episodic memories to semantic facts
3. Deduplicate near-identical memories
4. Adaptive decay with importance floor

Only runs when there are enough unconsolidated memories to justify the cost.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text

from nexus.config.settings import get_settings
from nexus.db.base import async_session
from nexus.db.models.memory import Memory
from nexus.db.repositories.base import GenericRepository
from nexus.llm.client import LLMClient
from nexus.memory.manager import MemoryManager
from nexus.memory.store import MemoryStore

logger = structlog.get_logger("nexus.memory.consolidator")

_CONSOLIDATION_PROMPT = """\
You are merging similar memory entries into a single coherent fact.

Memory entries:
{entries}

Generate a single consolidated fact that captures the essence of all these memories.
Be specific and avoid losing details. If there are contradictions, note them.
Keep it to 1-3 sentences."""

_PROMOTION_PROMPT = """\
Given these specific event descriptions, extract general factual statements
that remain true over time (not specific events):

Events:
{events}

Extract factual statements as a JSON list of strings:
["fact 1", "fact 2", ...]"""


@dataclass
class ConsolidationReport:
    """Report of a consolidation run."""

    clusters_merged: int = 0
    memories_promoted: int = 0
    duplicates_removed: int = 0
    memories_archived: int = 0
    errors: list[str] = field(default_factory=list)


class MemoryConsolidator:
    """Background memory consolidation and maintenance.

    Should be called periodically (every 30 min) when there are enough
    unconsolidated memories (> 10).
    """

    def __init__(
        self,
        store: MemoryStore | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self._store = store or MemoryStore()
        self._llm = llm or LLMClient()
        self._manager = MemoryManager(store=self._store, llm=self._llm)
        self._settings = get_settings().memory

    async def consolidate_all(self) -> ConsolidationReport:
        """Run the full consolidation pipeline.

        Only executes if there are enough active memories to justify the cost.
        Returns a report of actions taken.
        """
        report = ConsolidationReport()

        active_count = await self._count_active()
        if active_count < self._settings.consolidation_min_cluster * 5:
            logger.info("consolidator.skipped", active_count=active_count)
            return report

        try:
            merged = await self._cluster_and_merge()
            report.clusters_merged = merged

            promoted = await self._promote_to_semantic()
            report.memories_promoted = promoted

            deduped = await self._deduplicate()
            report.duplicates_removed = deduped

            archived = await self._adaptive_decay()
            report.memories_archived = archived

            logger.info("consolidator.complete", report=str(report))
        except Exception as exc:
            logger.error("consolidator.failed", error=str(exc))
            report.errors.append(str(exc))

        return report

    async def _count_active(self) -> int:
        """Count active (non-archived, non-deprecated) memories."""
        async with async_session() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM memory WHERE status = 'active' OR status IS NULL")
            )
            row = result.one()
            return int(row[0]) if row else 0

    async def _cluster_and_merge(self) -> int:
        """Cluster similar memories by embedding and merge clusters via LLM."""
        clusters = await self._find_embedding_clusters()
        if not clusters:
            return 0

        merged_count = 0
        for cluster in clusters:
            if len(cluster) < self._settings.consolidation_min_cluster:
                continue

            try:
                await self._merge_cluster(cluster)
                merged_count += 1
            except Exception as exc:
                logger.warning("consolidator.merge_failed", error=str(exc))

        return merged_count

    async def _find_embedding_clusters(self) -> list[list[dict[str, Any]]]:
        """Find clusters of similar memories using embedding pair similarity.

        Uses a simple greedy approach: for each memory, find all others
        above similarity threshold and group them.
        """
        async with async_session() as session:
            result = await session.execute(
                text("SELECT id, content, kind, importance, embedding FROM memory "
                     "WHERE (status = 'active' OR status IS NULL) AND embedding IS NOT NULL "
                     "ORDER BY importance DESC LIMIT 500")
            )
            rows = result.all()

        if len(rows) < self._settings.consolidation_min_cluster:
            return []

        memories = [
            {"id": str(r[0]), "content": r[1], "kind": r[2], "importance": float(r[3]),
             "embedding": r[4]}
            for r in rows
        ]

        threshold = self._settings.similarity_threshold - 0.05  # slightly lower for clustering
        clusters: list[list[dict[str, Any]]] = []
        assigned: set[str] = set()

        for mem in memories:
            if mem["id"] in assigned or not mem.get("embedding"):
                continue

            cluster = [mem]
            assigned.add(mem["id"])

            for other in memories:
                if other["id"] in assigned or not other.get("embedding"):
                    continue
                sim = self._cosine_sim(mem["embedding"], other["embedding"])
                if sim >= threshold:
                    cluster.append(other)
                    assigned.add(other["id"])

            if len(cluster) >= self._settings.consolidation_min_cluster:
                clusters.append(cluster)

        return clusters

    async def _merge_cluster(self, cluster: list[dict[str, Any]]) -> None:
        """Merge a cluster of memories into a single consolidated entry."""
        entries_text = "\n".join(f'- {m["content"]} (kind={m["kind"]})' for m in cluster)

        response = await self._llm.complete(
            model=get_settings().llm.default_model,
            messages=[
                {"role": "system", "content": _CONSOLIDATION_PROMPT.format(entries=entries_text)},
            ],
            temperature=0.2,
        )

        consolidated_content = (response.content or "").strip()
        if not consolidated_content:
            return

        max_importance = max(m["importance"] for m in cluster)
        consolidated_id = await self._manager._dedup_and_store(
            session_id="",
            kind="semantic",
            content=consolidated_content,
            importance=min(1.0, max_importance + 0.05),
        )

        # Deprecate source memories
        source_ids = [m["id"] for m in cluster]
        async with async_session() as session:
            for mid in source_ids:
                await session.execute(
                    text("UPDATE memory SET status = 'deprecated', metadata_ = "
                         "jsonb_set(COALESCE(metadata_, '{}'), '{consolidated_into}', "
                         f"'{json.dumps(consolidated_id)}'::jsonb) "
                         "WHERE id = :id"),
                    {"id": mid},
                )
            await session.commit()

        logger.info("consolidator.merged", source_count=len(source_ids), target_id=consolidated_id)

    async def _promote_to_semantic(self) -> int:
        """Promote high-importance episodic memories to semantic facts."""
        async with async_session() as session:
            result = await session.execute(
                text("SELECT id, content FROM memory WHERE kind = 'episodic' AND "
                     "importance >= 0.7 AND (status = 'active' OR status IS NULL) "
                     "LIMIT 50")
            )
            episodes = [{"id": str(r[0]), "content": r[1]} for r in result.all()]

        if len(episodes) < 2:
            return 0

        events_text = "\n".join(f'- {e["content"]}' for e in episodes)

        response = await self._llm.complete(
            model=get_settings().llm.default_model,
            messages=[
                {"role": "system", "content": _PROMOTION_PROMPT.format(events=events_text)},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )

        try:
            data = json.loads(response.content or "[]")
            facts = data if isinstance(data, list) else data.get("facts", [])
        except (json.JSONDecodeError, TypeError):
            return 0

        promoted = 0
        for fact in facts:
            if isinstance(fact, str) and fact.strip():
                await self._manager._dedup_and_store(
                    session_id="",
                    kind="semantic",
                    content=fact.strip(),
                    importance=0.6,
                )
                promoted += 1

        return promoted

    async def _deduplicate(self) -> int:
        """Find and remove near-exact duplicate memories (cosine > 0.95)."""
        async with async_session() as session:
            result = await session.execute(
                text("SELECT id, content, importance, embedding FROM memory "
                     "WHERE (status = 'active' OR status IS NULL) AND embedding IS NOT NULL "
                     "ORDER BY importance DESC LIMIT 200")
            )
            rows = result.all()

        if len(rows) < 2:
            return 0

        memories = [
            {"id": str(r[0]), "content": r[1], "importance": float(r[2]), "embedding": r[3]}
            for r in rows
        ]

        threshold = 0.95
        removed = 0

        for i in range(len(memories)):
            if not memories[i].get("embedding"):
                continue
            for j in range(i + 1, len(memories)):
                if not memories[j].get("embedding"):
                    continue
                sim = self._cosine_sim(memories[i]["embedding"], memories[j]["embedding"])
                if sim >= threshold:
                    # Keep higher-importance one, deprecate the other
                    keep, dep = (memories[i], memories[j]) if memories[i]["importance"] >= memories[j]["importance"] else (memories[j], memories[i])
                    async with async_session() as session:
                        await session.execute(
                            text("UPDATE memory SET status = 'deprecated' WHERE id = :id"),
                            {"id": dep["id"]},
                        )
                        await session.commit()
                    removed += 1

        return removed

    async def _adaptive_decay(self) -> int:
        """Apply adaptive decay based on access frequency, recency, and importance.

        Decay rate = base_rate × access_factor × recency_factor × importance_factor
        """
        settings = self._settings
        base_rate = settings.decay_base_rate
        floor = settings.decay_importance_floor
        archive_threshold = settings.decay_archive_threshold

        async with async_session() as session:
            result = await session.execute(
                text("SELECT id, importance, last_accessed_at, access_count, base_importance, "
                     "metadata_ FROM memory WHERE (status = 'active' OR status IS NULL)")
            )
            rows = result.all()

        if not rows:
            return 0

        # Compute average access count for normalization
        access_counts = [int(r[3]) if r[3] else 0 for r in rows]
        avg_access = sum(access_counts) / len(access_counts) if access_counts else 1
        now = datetime.now(UTC)
        archived = 0

        for row in rows:
            mid = row[0]
            current_imp = float(row[1])
            last_access = row[2]
            access_count = int(row[3]) if row[3] else 0
            base_imp = float(row[4]) if row[4] else current_imp
            meta = dict(row[5]) if row[5] else {}

            rate = base_rate

            # Factor: access frequency (frequently accessed decays slower)
            if access_count > avg_access:
                rate *= 0.5

            # Factor: recency (accessed within 24h decays much slower)
            if last_access:
                hours_since = (now - last_access).total_seconds() / 3600
                if hours_since < 24:
                    rate *= 0.3
                elif hours_since < 168:  # 1 week
                    rate *= 0.7

            # Factor: importance ceiling (important decays slower)
            rate *= (1.0 - min(base_imp, 0.9))

            new_importance = max(floor, current_imp - rate * current_imp)

            # Archive if below threshold
            if new_importance < archive_threshold:
                meta["archived"] = True
                archived += 1

            async with async_session() as session:
                repo = GenericRepository(session, Memory)
                await repo.update(
                    mid,
                    importance=new_importance,
                    current_importance=new_importance,
                    metadata_=meta,
                )
                await session.commit()

        logger.info("consolidator.decay_complete", archived=archived, processed=len(rows))
        return archived

    @staticmethod
    def _cosine_sim(a: Any, b: Any) -> float:
        """Compute cosine similarity between two embedding vectors."""
        if a is None or b is None:
            return 0.0
        vec_a = list(a) if hasattr(a, '__iter__') else []
        vec_b = list(b) if hasattr(b, '__iter__') else []
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0
        dot = sum(x * y for x, y in zip(vec_a, vec_b))
        norm_a = sum(x * x for x in vec_a) ** 0.5
        norm_b = sum(y * y for y in vec_b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
