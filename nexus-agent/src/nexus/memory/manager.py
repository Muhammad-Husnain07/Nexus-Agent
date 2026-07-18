"""MemoryManager — service for extracting, storing, and retrieving long-term memories.

Coordinates between the ``EpisodicSummarizer``, ``MemoryStore``, and the LLM
to extract salient information from agent runs, deduplicate against existing
memories, and serve relevant context to future sessions.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text

from nexus.config.settings import get_settings
from nexus.db.base import async_session
from nexus.db.models.memory import Memory
from nexus.db.repositories.base import TenantScopedRepository
from nexus.llm.client import LLMClient, LLMResponse
from nexus.memory.store import MemoryStore
from nexus.memory.summarizer import EpisodicSummarizer

logger = structlog.get_logger("nexus.memory.manager")

_EXTRACT_SYSTEM_PROMPT = """\
You are a memory extraction system. Review the agent run transcript below and
extract salient information that should be remembered for future interactions.

For each memory, identify:
- **kind**: one of "preference", "fact", "decision", or "procedure"
- **content**: 1-2 sentence description of what to remember
- **importance**: 0.0-1.0 score (1.0 = critical, 0.3 = minor detail)

Return a JSON list:
[
  {"kind": "preference|fact|decision|procedure", "content": "...", "importance": 0.0},
  ...
]

If nothing is worth remembering, return an empty list [].
"""


class MemoryManager:
    """High-level service for long-term memory operations."""

    def __init__(
        self,
        store: MemoryStore | None = None,
        summarizer: EpisodicSummarizer | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self._store = store or MemoryStore()
        self._summarizer = summarizer or EpisodicSummarizer(llm=llm)
        self._llm = llm or LLMClient()
        self._settings = get_settings()
        self._memory_settings = self._settings.memory

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    async def extract_and_store(
        self,
        tenant_id: str,
        user_id: str,
        session_id: str,
        agent_run_id: str | None = None,
        agent_state: dict[str, Any] | None = None,
    ) -> list[str]:
        """Extract salient memories from an agent run and persist them.

        Args:
            tenant_id: Tenant UUID string.
            user_id: User UUID string.
            session_id: Session UUID string.
            agent_run_id: Optional agent run UUID string.
            agent_state: The final ``AgentState`` dict from the run.

        Returns:
            List of memory IDs that were stored or updated.
        """
        if not self._memory_settings.enabled:
            logger.info("memory.extract_skipped_disabled")
            return []

        transcript = self._build_transcript(agent_state)
        memories_raw = await self._extract_from_llm(transcript)

        stored_ids: list[str] = []
        for mem in memories_raw:
            mid = await self._dedup_and_store(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                kind=mem["kind"],
                content=mem["content"],
                importance=min(1.0, max(0.0, mem.get("importance", 0.5))),
            )
            if mid:
                stored_ids.append(mid)

        # Also store an episodic summary
        summary = await self._summarizer.summarize(agent_state or {})
        summary_id = await self._dedup_and_store(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            kind="episodic",
            content=summary,
            importance=0.6,
        )
        if summary_id:
            stored_ids.append(summary_id)

        logger.info(
            "memory.extracted",
            count=len(stored_ids),
            session_id=session_id,
        )
        return stored_ids

    async def _extract_from_llm(self, transcript: str) -> list[dict[str, Any]]:
        """Call the LLM to extract structured memories from a transcript."""
        if not transcript.strip():
            return []

        response: LLMResponse = await self._llm.complete(
            model=self._settings.llm.default_model,
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": f"Transcript:\n{transcript[:8000]}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )

        try:
            data = json.loads(response.content or "[]")
            if isinstance(data, dict):
                data = data.get("memories", [])
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            logger.warning("memory.extract_parse_failed")
            return []

    async def _dedup_and_store(  # noqa: PLR0913
        self,
        tenant_id: str,
        user_id: str,
        session_id: str,
        kind: str,
        content: str,
        importance: float,
    ) -> str | None:
        """Deduplicate against existing memories, then store.

        If a similar memory (cosine > ``similarity_threshold``) exists
        with the same kind, the existing entry is updated instead of
        creating a duplicate.
        """
        mid = uuid.uuid4()
        embedding = await self._generate_embedding(content)

        if embedding and self._memory_settings.similarity_threshold > 0:
            similar = await self._store.search(
                query_embedding=embedding,
                namespace=(tenant_id, "memories", kind),
                top_k=1,
                metadata_filter={"user_id": user_id},
            )
            sim = self._memory_settings.similarity_threshold
            if similar and similar[0].get("similarity", 0) >= sim:
                existing_id = uuid.UUID(similar[0]["id"])
                logger.info("memory.dedup_merged", existing_id=str(existing_id), kind=kind)
                await self._store.put(
                    namespace=(tenant_id, "memories", kind),
                    memory_id=existing_id,
                    content=content,
                    embedding=embedding,
                    metadata={"user_id": user_id, "session_id": session_id},
                    importance=importance,
                )
                return str(existing_id)

        await self._store.put(
            namespace=(tenant_id, "memories", kind),
            memory_id=mid,
            content=content,
            embedding=embedding,
            metadata={"user_id": user_id, "session_id": session_id},
            importance=importance,
        )
        return str(mid)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    async def retrieve_relevant(
        self,
        tenant_id: str,
        user_id: str,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search for memories relevant to *query*.

        Args:
            tenant_id: Tenant UUID string.
            user_id: User UUID string.
            query: Natural-language query (e.g. user's current message).
            top_k: Max results (defaults to ``memory.retrieval_top_k``).

        Returns:
            List of matching memory dicts with ``similarity``.
        """
        if not self._memory_settings.enabled:
            return []

        k = top_k or self._memory_settings.retrieval_top_k
        embedding = await self._generate_embedding(query)
        if embedding is None:
            return []

        return await self._store.search(
            query_embedding=embedding,
            top_k=k,
            metadata_filter={"user_id": user_id},
        )

    async def retrieve_formatted(
        self,
        tenant_id: str,
        user_id: str,
        query: str,
    ) -> str:
        """Retrieve memories and format them as a system-prompt block."""
        memories = await self.retrieve_relevant(tenant_id, user_id, query)
        if not memories:
            return ""

        lines = ["# Relevant past memories\n"]
        for m in memories:
            lines.append(f"- [{m['kind']}] (importance {m['importance']:.1f}): {m['content']}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Decay
    # ------------------------------------------------------------------

    async def decay(self, days_threshold: int = 90) -> int:
        """Reduce importance of stale memories.

        Memories not accessed in *days_threshold* days have their importance
        halved.  Those falling below ``importance_threshold`` are archived
        (marked with ``archived: true`` in metadata).

        Args:
            days_threshold: Age in days for a memory to be considered stale.

        Returns:
            Number of memories archived.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days_threshold)
        threshold = self._memory_settings.importance_threshold
        archived = 0

        async with async_session() as session:
            repo = TenantScopedRepository(session, Memory)
            stmt = "SELECT id, importance, last_accessed_at, metadata_ FROM memory"
            result = await session.execute(text(stmt))
            rows = result.all()

            for row in rows:
                mid = row[0]
                importances = float(row[1])
                last_access = row[2]
                meta = row[3] or {}

                if last_access is None or last_access < cutoff:
                    new_importance = importances / 2.0
                    if new_importance < threshold:
                        meta["archived"] = True
                        archived += 1
                    await repo.update(
                        mid,
                        importance=max(0.0, new_importance),
                        metadata_=meta,
                    )

            await session.commit()

        logger.info("memory.decay_complete", archived=archived)
        return archived

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def _generate_embedding(self, text_content: str) -> list[float] | None:
        """Generate an embedding vector via the configured embedding model."""
        if not text_content.strip():
            return None
        try:
            response = await self._llm.complete(
                model=self._settings.llm.embedding_model,
                messages=[{"role": "user", "content": text_content}],
                temperature=0,
            )
            raw = (response.content or "").strip()
            if raw.startswith("[") and raw.endswith("]"):
                return json.loads(raw)
            return None
        except Exception as exc:
            logger.warning("memory.embedding_failed", error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_transcript(agent_state: dict[str, Any] | None) -> str:
        """Build a compact transcript from agent state."""
        if not agent_state:
            return ""
        messages = agent_state.get("messages", [])
        tool_results = agent_state.get("tool_results", [])
        plan = agent_state.get("plan", [])
        errors = agent_state.get("errors", [])
        intent = agent_state.get("intent", {})

        parts = [f"Intent: {json.dumps(intent)}"]
        for msg in messages[-10:]:
            role = msg.get("role", "?")
            content = msg.get("content", "")[:300]
            parts.append(f"{role}: {content}")

        if plan:
            parts.append(f"Steps: {len(plan)}")

        if tool_results:
            last = tool_results[-1]
            parts.append(f"Final tool: {last.get('tool_name', '?')} ({last.get('status', '?')})")

        if errors:
            parts.append(f"Errors: {'; '.join(errors[-3:])}")

        return "\n".join(parts)
