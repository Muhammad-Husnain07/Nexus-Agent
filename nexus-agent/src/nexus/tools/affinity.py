"""ToolAffinityGraph — tracks tool co-occurrence for composition hints and fallback chains.

Uses Redis ZSETs for fast runtime lookups and PostgreSQL for durability.
Edges represent P(target_tool | source_tool) — the probability that target_tool
is called within a window after source_tool.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import structlog

from nexus.config.settings import get_settings
from nexus.redis_client.client import get_redis_client

logger = structlog.get_logger("nexus.tools.affinity")

_REDIS_PREFIX = "affinity:"
_DEFAULT_WINDOW = 5


def _affinity_key(tool_name: str) -> str:
    return f"{_REDIS_PREFIX}{tool_name}"


class ToolAffinityGraph:
    """Tracks which tools are frequently called together.

    Maintains a directed graph where:
    - Nodes = tool names
    - Edge weights = P(target_tool | source_tool) (conditional probability)

    Uses Redis ZSETs for fast lookups and PostgreSQL for durability.
    """

    def __init__(self) -> None:
        self._redis = get_redis_client()
        self._co_occurrence: dict[tuple[str, str], int] = defaultdict(int)
        self._tool_counts: dict[str, int] = defaultdict(int)
        self._window_size: int = getattr(get_settings().tools, "affinity_window_size", _DEFAULT_WINDOW)
        self._dirty: bool = False

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_execution(self, tool_sequence: list[str], success: bool = True) -> None:
        """Record a sequence of tool calls from a successful run.

        Updates in-memory counters and Redis ZSETs for fast future lookups.
        """
        if not tool_sequence or not success:
            return

        unique_tools = list(dict.fromkeys(tool_sequence))

        for i, source in enumerate(unique_tools):
            self._tool_counts[source] += 1
            window_end = min(i + self._window_size + 1, len(unique_tools))
            for j in range(i + 1, window_end):
                target = unique_tools[j]
                if source != target:
                    self._co_occurrence[(source, target)] += 1

        self._dirty = True
        self._flush_to_redis(unique_tools)

    def _flush_to_redis(self, tools: list[str]) -> None:
        """Push latest affinity scores to Redis ZSETs."""
        if self._redis is None:
            return

        seen_sources: set[str] = set()
        for source, target in self._co_occurrence:
            if source in seen_sources and target in seen_sources:
                continue
            weight = self.affinity(source, target)
            if weight > 0:
                key = _affinity_key(source)
                self._redis.zadd(key, {target: weight})
                seen_sources.add(source)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def affinity(self, source: str, target: str) -> float:
        """Conditional probability P(target | source)."""
        pair_count = self._co_occurrence.get((source, target), 0)
        src_count = self._tool_counts.get(source, 0)
        if src_count == 0:
            return 0.0
        return pair_count / src_count

    def pmi(self, source: str, target: str) -> float:
        """Pointwise Mutual Information — how much more than random chance."""
        total = sum(self._tool_counts.values())
        if total == 0:
            return 0.0
        p_a = self._tool_counts.get(source, 0) / total
        p_b = self._tool_counts.get(target, 0) / total
        p_ab = self._co_occurrence.get((source, target), 0) / total
        if p_ab <= 0 or p_a <= 0 or p_b <= 0:
            return 0.0
        return math.log(p_ab / (p_a * p_b))

    def suggest_compositions(self, seed_tool: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Suggest tools that are frequently called after seed_tool."""
        candidates: list[tuple[str, float]] = []

        # Check Redis first
        if self._redis is not None:
            key = _affinity_key(seed_tool)
            results = self._redis.zrevrange(key, 0, top_k - 1, withscores=True)
            if results:
                return [(r[0].decode() if isinstance(r[0], bytes) else r[0], float(r[1])) for r in results]

        # Fall back to in-memory
        for (src, tgt), count in self._co_occurrence.items():
            if src == seed_tool:
                candidates.append((tgt, self.affinity(seed_tool, tgt)))

        candidates.sort(key=lambda x: -x[1])
        return candidates[:top_k]

    def get_fallback_chain(self, tool: str, max_fallbacks: int = 3) -> list[str]:
        """Return the best fallback tools for when *tool* fails.

        Uses schema compatibility + affinity to rank alternatives.
        """
        compositions = self.suggest_compositions(tool, top_k=max_fallbacks * 2)
        return [t for t, _ in compositions[:max_fallbacks]]

    def build_composition_hints(self, tools: list[dict[str, Any]], max_hints: int = 3) -> str:
        """Generate prompt text like 'When doing X, try: tool_A → tool_B'."""
        hints: list[str] = []
        seen_pairs: set[tuple[str, str]] = set()

        for tool in tools:
            name = tool.get("name", "")
            if not name:
                continue
            successors = self.suggest_compositions(name, top_k=2)
            for succ, weight in successors:
                if weight < 0.1 or (name, succ) in seen_pairs:
                    continue
                seen_pairs.add((name, succ))
                hints.append(f"- {name} → {succ} (affinity: {weight:.2f})")
                if len(hints) >= max_hints:
                    break
            if len(hints) >= max_hints:
                break

        if not hints:
            return ""

        return "<composition_hints>\n" + "\n".join(hints) + "\n</composition_hints>"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def persist_to_postgres(self) -> None:
        """Flush in-memory affinity data to PostgreSQL."""
        if not self._dirty:
            return
        try:
            from sqlalchemy import text as sql_text  # noqa: PLC0415
            from nexus.db.base import async_session  # noqa: PLC0415

            async with async_session() as session:
                for (source, target), count in self._co_occurrence.items():
                    weight = self.affinity(source, target)
                    pmi_val = self.pmi(source, target)
                    await session.execute(
                        sql_text(
                            "INSERT INTO affinity_edges (source, target, weight, pmi, success_count, updated_at) "
                            "VALUES (:s, :t, :w, :p, :c, NOW()) "
                            "ON CONFLICT (source, target) DO UPDATE SET "
                            "weight = :w, pmi = :p, success_count = affinity_edges.success_count + :c, updated_at = NOW()"
                        ),
                        {"s": source, "t": target, "w": weight, "p": pmi_val, "c": count},
                    )
                await session.commit()
            self._dirty = False
            logger.info("affinity.persisted", edges=len(self._co_occurrence))
        except Exception as exc:
            logger.warning("affinity.persist_failed", error=str(exc))

    async def load_from_postgres(self) -> None:
        """Load affinity edges from PostgreSQL into memory on startup."""
        try:
            from sqlalchemy import text as sql_text  # noqa: PLC0415
            from nexus.db.base import async_session  # noqa: PLC0415

            async with async_session() as session:
                result = await session.execute(
                    sql_text("SELECT source, target, success_count FROM affinity_edges ORDER BY weight DESC LIMIT 5000")
                )
                rows = result.all()
                for row in rows:
                    source, target, count = str(row[0]), str(row[1]), int(row[2])
                    self._co_occurrence[(source, target)] += count
                    self._tool_counts[source] += count

            self._flush_to_redis(list(set(s for s, _ in self._co_occurrence)))
            logger.info("affinity.loaded", edges=len(self._co_occurrence))
        except Exception as exc:
            logger.warning("affinity.load_failed", error=str(exc))


affinity_graph = ToolAffinityGraph()
"""Default singleton ToolAffinityGraph instance."""
