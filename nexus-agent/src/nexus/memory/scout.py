"""MemoryScout — proactive memory retrieval at strategic trigger points.

Replaces the current single-trigger retrieval (only on understand_intent) with
a multi-trigger system that injects relevant memories at:
1. Intent analysis (after understanding user goal)
2. Tool result (after tool batch completes)
3. Final composition (before final response)
4. Requirements gathering (before asking questions)

Uses Maximum Marginal Relevance (MMR) for diverse, non-redundant results.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient
from nexus.memory.manager import MemoryManager
from nexus.memory.store import MemoryStore

logger = structlog.get_logger("nexus.memory.scout")

TRIGGER_INTENT = "intent"
TRIGGER_TOOL_RESULT = "tool_result"
TRIGGER_FINALIZE = "finalize"
TRIGGER_GATHER = "gather"


class MemoryScout:
    """Proactive memory retrieval — injects relevant memories without explicit queries.

    Usage::

        scout = MemoryScout(llm=llm_client)
        memory_context = await scout.scout(
            trigger=TRIGGER_INTENT,
            context={"intent": "check weather", "query": "what's the weather in London"},
        )
        if memory_context:
            prompt = memory_context + "\\n" + prompt
    """

    def __init__(
        self,
        llm: LLMClient | None = None,
        store: MemoryStore | None = None,
    ) -> None:
        self._llm = llm
        self._manager = MemoryManager(store=store or MemoryStore(), llm=llm)
        self._settings = get_settings().memory

    async def scout(
        self,
        trigger: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Check if memory retrieval is needed and return formatted memory context.

        Args:
            trigger: One of TRIGGER_* constants.
            context: Dict with trigger-specific keys (intent, query, tool_name, etc.).

        Returns:
            Formatted memory XML block (empty string if nothing relevant).
        """
        if not self._settings.scout_enabled or not self._settings.enabled:
            return ""

        query = self._build_query(trigger, context or {})
        if not query:
            return ""

        memories = await self._retrieve_mmr(query)
        if not memories:
            return ""

        return self._format(memories)

    def _build_query(self, trigger: str, context: dict[str, Any]) -> str:
        """Build an implicit search query from the trigger context."""
        if trigger == TRIGGER_INTENT:
            return context.get("intent") or context.get("query", "")

        if trigger == TRIGGER_TOOL_RESULT:
            tool_name = context.get("tool_name", "")
            result_summary = str(context.get("result_summary", ""))
            return f"{tool_name}: {result_summary}" if tool_name else result_summary

        if trigger == TRIGGER_FINALIZE:
            intent = context.get("intent", "")
            results = context.get("tool_results", [])
            if results:
                last = results[-1] if isinstance(results, list) else results
                tool = last.get("tool_name", "") if isinstance(last, dict) else ""
                return f"{intent} {tool}".strip()
            return intent

        if trigger == TRIGGER_GATHER:
            missing = context.get("missing_slots", [])
            return f"Need information about: {', '.join(missing)}" if missing else ""

        return ""

    async def _retrieve_mmr(self, query: str) -> list[dict[str, Any]]:
        """Retrieve memories with Maximum Marginal Relevance for diversity."""
        embedding = await self._manager._generate_embedding(query)
        if embedding is None:
            return []

        k = self._settings.retrieval_top_k
        mmr_lambda = self._settings.scout_mmr_lambda

        # Get candidate pool
        candidates = await self._manager._store.search(
            query_embedding=embedding,
            top_k=k * 4,  # larger pool for MMR selection
        )
        if not candidates:
            return []
        if len(candidates) <= k:
            return candidates

        # MMR selection
        selected: list[dict[str, Any]] = []
        remaining = list(candidates)

        # Pick first: highest similarity
        selected.append(remaining.pop(0))

        while len(selected) < k and remaining:
            best_idx = 0
            best_score = -float("inf")

            for i, cand in enumerate(remaining):
                relevance = cand.get("similarity", 0)

                max_sim = 0.0
                for sel in selected:
                    sim = self._cosine_sim_approx(cand, sel)
                    if sim > max_sim:
                        max_sim = sim

                mmr_score = mmr_lambda * relevance - (1 - mmr_lambda) * max_sim
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = i

            selected.append(remaining.pop(best_idx))

        return selected

    def _format(self, memories: list[dict[str, Any]]) -> str:
        """Format retrieved memories as an XML block constrained by token budget."""
        max_tokens = self._settings.scout_max_injection_tokens
        parts: list[str] = ["<retrieved_memories>"]

        token_count = 0
        for mem in memories:
            kind = mem.get("kind", "unknown")
            content = mem.get("content", "")
            importance = mem.get("importance", 0)

            entry = f'<memory kind="{kind}" importance="{importance:.1f}">{content}</memory>'
            estimated_tokens = len(entry) // 4  # rough estimate

            if token_count + estimated_tokens > max_tokens:
                break

            parts.append(entry)
            token_count += estimated_tokens

        parts.append("</retrieved_memories>")
        return "\n".join(parts) if len(parts) > 2 else ""

    @staticmethod
    def _cosine_sim_approx(a: dict[str, Any], b: dict[str, Any]) -> float:
        """Approximate similarity using the precomputed query similarity as proxy."""
        return min(a.get("similarity", 0), b.get("similarity", 0)) * 0.5
