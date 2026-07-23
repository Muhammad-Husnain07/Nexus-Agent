"""MemoryManager — service for extracting, storing, and retrieving long-term memories."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text

from nexus.config.settings import get_settings
from nexus.db.base import async_session
from nexus.db.models.memory import Memory
from nexus.db.repositories.base import GenericRepository
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

    async def extract_and_store(
        self,
        session_id: str,
        agent_run_id: str | None = None,
        agent_state: dict[str, Any] | None = None,
    ) -> list[str]:
        """Extract salient memories from an agent run and persist them."""
        if not self._memory_settings.enabled:
            logger.info("memory.extract_skipped_disabled")
            return []

        transcript = self._build_transcript(agent_state)
        memories_raw = await self._extract_from_llm(transcript)

        stored_ids: list[str] = []
        for mem in memories_raw:
            mid = await self._dedup_and_store(
                session_id=session_id,
                kind=mem["kind"],
                content=mem["content"],
                importance=min(1.0, max(0.0, mem.get("importance", 0.5))),
            )
            if mid:
                stored_ids.append(mid)

        summary = await self._summarizer.summarize(agent_state or {})
        summary_id = await self._dedup_and_store(
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

    async def _dedup_and_store(
        self,
        session_id: str,
        kind: str,
        content: str,
        importance: float,
    ) -> str | None:
        """Deduplicate against existing memories, then store."""
        # Sanitize content — strip LLM artifacts before persistence
        content = re.sub(r"###\s*$", "", content.strip())
        content = re.sub(r"<\|im_end\|>\s*$", "", content.strip())
        content = re.sub(r"<\|endoftext\|>\s*$", "", content.strip())

        mid = uuid.uuid4()
        embedding = await self._generate_embedding(content)

        if embedding and self._memory_settings.similarity_threshold > 0:
            similar = await self._store.search(
                query_embedding=embedding,
                kind=kind,
                top_k=1,
            )
            sim = self._memory_settings.similarity_threshold
            if similar and similar[0].get("similarity", 0) >= sim:
                existing_id = uuid.UUID(similar[0]["id"])
                logger.info("memory.dedup_merged", existing_id=str(existing_id), kind=kind)
                await self._store.put(
                    session_id=session_id,
                    memory_id=existing_id,
                    kind=kind,
                    content=content,
                    embedding=embedding,
                    metadata={"session_id": session_id},
                    importance=importance,
                )
                return str(existing_id)

        await self._store.put(
            session_id=session_id,
            memory_id=mid,
            kind=kind,
            content=content,
            embedding=embedding,
            metadata={"session_id": session_id},
            importance=importance,
        )
        return str(mid)

    async def retrieve_relevant(
        self,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search for memories relevant to *query*."""
        if not self._memory_settings.enabled:
            return []

        k = top_k or self._memory_settings.retrieval_top_k
        embedding = await self._generate_embedding(query)
        if embedding is None:
            return []

        return await self._store.search(
            query_embedding=embedding,
            top_k=k,
        )

    async def retrieve_mmr(
        self,
        query: str,
        top_k: int | None = None,
        mmr_lambda: float | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve memories with Maximum Marginal Relevance for diversity.

        Args:
            query: Search query text.
            top_k: Number of results (default from settings).
            mmr_lambda: MMR diversity weight (0=all diverse, 1=all relevant).

        Returns:
            List of diverse, relevant memory dicts.
        """
        if not self._memory_settings.enabled:
            return []

        k = top_k or self._memory_settings.retrieval_top_k
        lam = mmr_lambda if mmr_lambda is not None else self._memory_settings.scout_mmr_lambda

        embedding = await self._generate_embedding(query)
        if embedding is None:
            return []

        # Get larger candidate pool for MMR
        candidates = await self._store.search(
            query_embedding=embedding,
            top_k=k * 4,
        )
        if not candidates:
            return []
        if len(candidates) <= k:
            return candidates

        selected: list[dict[str, Any]] = []
        remaining = list(candidates)
        selected.append(remaining.pop(0))

        while len(selected) < k and remaining:
            best_idx = 0
            best_score = -float("inf")

            for i, cand in enumerate(remaining):
                relevance = cand.get("similarity", 0)
                max_sim = max(
                    (sel.get("similarity", 0) for sel in selected),
                    default=0,
                )
                mmr = lam * relevance - (1 - lam) * max_sim
                if mmr > best_score:
                    best_score = mmr
                    best_idx = i

            selected.append(remaining.pop(best_idx))

        return selected

    async def retrieve_formatted(
        self,
        query: str,
    ) -> str:
        """Retrieve memories and format them as structured few-shot examples."""
        memories = await self.retrieve_relevant(query)
        if not memories:
            return ""

        lines: list[str] = ["# Relevant past interactions — use as reference\n"]
        for m in memories:
            kind = m.get("kind", "unknown")
            content = m.get("content", "")
            meta = m.get("metadata", {}) or {}

            if kind == "episodic":
                lines.append("## Example from past interaction")
                outcome = "Success" if "success" in content.lower() else "Completed"
                tool_hint = meta.get("tool_name", "")
                if tool_hint:
                    lines.append(f"Tools used: {tool_hint} → {outcome}")
                lines.append(f"Context: {content}")
                lines.append("")

            elif kind in ("preference", "fact", "semantic"):
                lines.append(f"- Known: {content}")
                lines.append("")

            elif kind in ("decision", "procedure"):
                lines.append(f"- Rule: {content}")
                lines.append("")

        return "\n".join(lines) if len(lines) > 1 else ""

    async def decay(self, days_threshold: int = 90) -> int:
        """Reduce importance of stale memories."""
        cutoff = datetime.now(UTC) - timedelta(days=days_threshold)
        threshold = self._memory_settings.importance_threshold
        archived = 0

        async with async_session() as session:
            repo = GenericRepository(session, Memory)
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

    async def _generate_embedding(self, text_content: str) -> list[float] | None:
        """Generate an embedding vector via the configured embedding model."""
        if not text_content.strip():
            return None
        try:
            embeddings = await self._llm.embed(
                self._settings.llm.embedding_model,
                [text_content],
            )
            if embeddings and len(embeddings) > 0 and embeddings[0]:
                return embeddings[0]
            logger.warning("memory.embedding_empty", model=self._settings.llm.embedding_model)
            return None
        except Exception as exc:
            logger.warning("memory.embedding_failed", error=str(exc))
            return None

    @staticmethod
    def _msg_role(msg: Any) -> str:
        """Extract role from dict or BaseMessage."""
        if isinstance(msg, dict):
            return str(msg.get("role", "?"))
        return str(getattr(msg, "type", "?")) if not isinstance(msg, str) else "?"

    @staticmethod
    def _msg_content(msg: Any) -> str:
        """Extract content from dict or BaseMessage."""
        if isinstance(msg, dict):
            return str(msg.get("content", ""))
        return str(getattr(msg, "content", "")) if not isinstance(msg, str) else ""

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
            role = MemoryManager._msg_role(msg)
            content = MemoryManager._msg_content(msg)[:300]
            parts.append(f"{role}: {content}")

        if plan:
            parts.append(f"Steps: {len(plan)}")

        if tool_results:
            last = tool_results[-1]
            parts.append(f"Final tool: {last.get('tool_name', '?')} ({last.get('status', '?')})")

        if errors:
            parts.append(f"Errors: {'; '.join(errors[-3:])}")

        return "\n".join(parts)
