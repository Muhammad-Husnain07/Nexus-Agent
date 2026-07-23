"""Long-term memory store backed by the ``Memory`` SQLAlchemy model with pgvector."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from sqlalchemy import text

from nexus.db.base import async_session
from nexus.db.models.memory import Memory
from nexus.db.repositories.base import GenericRepository

logger = structlog.get_logger("nexus.memory.store")

MemoryKind = Literal["episodic", "semantic", "procedural", "preference"]


class MemoryStore:
    """Postgres-backed memory store with vector similarity search."""

    def __init__(self) -> None:
        pass

    async def put(  # noqa: PLR0913
        self,
        session_id: str | None = None,
        memory_id: uuid.UUID | None = None,
        kind: str = "semantic",
        content: str = "",
        embedding: list[float] | None = None,
        metadata: dict[str, Any] | None = None,
        importance: float = 0.5,
    ) -> uuid.UUID:
        """Store a memory entry."""
        mid = memory_id or uuid.uuid4()

        # Sanitize content before persisting — strip LLM artifacts
        content = re.sub(r"###\s*$", "", content.strip())
        content = re.sub(r"<\|im_end\|>\s*$", "", content.strip())
        content = re.sub(r"<\|endoftext\|>\s*$", "", content.strip())

        async with async_session() as session:
            repo = GenericRepository(session, Memory)
            existing = await repo.get(mid)
            if existing is not None:
                existing.content = content
                existing.importance = importance
                existing.metadata_ = metadata or {}
                existing.last_accessed_at = datetime.now(UTC)
                if embedding is not None:
                    existing.embedding = embedding
            else:
                now = datetime.now(UTC)
                await repo.create(
                    id=mid,
                    session_id=uuid.UUID(session_id) if session_id else None,
                    kind=kind,
                    content=content,
                    embedding=embedding,
                    metadata_=metadata or {},
                    importance=importance,
                    status="active",
                    access_count=0,
                    base_importance=importance,
                    current_importance=importance,
                    created_at=now,
                )
            await session.commit()
        return mid

    async def get(
        self, memory_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """Retrieve a single memory by ID."""
        async with async_session() as session:
            repo = GenericRepository(session, Memory)
            mem = await repo.get(memory_id)
            if mem is None:
                return None
            mem.last_accessed_at = datetime.now(UTC)
            await session.commit()
            return self._row_to_dict(mem)

    async def search(
        self,
        query_embedding: list[float],
        kind: str | None = None,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search over stored memories."""
        vec_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"
        sql = "SELECT id, session_id, kind, content, metadata_, importance, "
        sql += "created_at, last_accessed_at, "
        sql += f"1 - (embedding <=> '{vec_literal}'::vector) AS similarity "
        sql += "FROM memory WHERE 1=1 "
        params: dict[str, Any] = {}

        if kind:
            sql += "AND kind = :kind "
            params["kind"] = kind

        if metadata_filter:
            import re
            _VALID_KEY = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
            for idx, (k, v) in enumerate(metadata_filter.items()):
                if not _VALID_KEY.fullmatch(str(k)):
                    raise ValueError(f"Invalid metadata key: {k}")
                kp = f"mfk_{idx}"
                vp = f"mfv_{idx}"
                sql += f"AND metadata_ ->> :{kp} = :{vp} "
                params[kp] = k
                params[vp] = str(v)

        sql += "ORDER BY similarity DESC LIMIT :top_k"
        params["top_k"] = top_k

        async with async_session() as session:
            result = await session.execute(text(sql), params)
            rows = result.all()

        output: list[dict[str, Any]] = []
        for row in rows:
            d = {
                "id": str(row[0]),
                "session_id": str(row[1]) if row[1] else None,
                "kind": row[2],
                "content": row[3],
                "metadata": row[4],
                "importance": float(row[5]),
                "created_at": str(row[6]) if row[6] else None,
                "last_accessed_at": str(row[7]) if row[7] else None,
                "similarity": float(row[8]),
            }
            output.append(d)

        # Update last_accessed_at and access_count for retrieved memories
        if rows:
            ids = [str(r[0]) for r in rows]
            update_sql = (
                "UPDATE memory SET last_accessed_at = NOW(), "
                "access_count = COALESCE(access_count, 0) + 1 "
                "WHERE id = ANY(:ids)"
            )
            async with async_session() as session:
                await session.execute(text(update_sql), {"ids": ids})
                await session.commit()

        return output

    async def delete(self, memory_id: uuid.UUID) -> bool:
        """Delete a memory by ID."""
        async with async_session() as session:
            repo = GenericRepository(session, Memory)
            deleted = await repo.delete(memory_id)
            if deleted:
                await session.commit()
            return deleted

    @staticmethod
    def _row_to_dict(row: Memory) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "session_id": str(row.session_id) if row.session_id else None,
            "kind": row.kind,
            "content": row.content,
            "metadata": row.metadata_,
            "importance": row.importance,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "last_accessed_at": row.last_accessed_at.isoformat() if row.last_accessed_at else None,
            "status": row.status,
            "access_count": row.access_count,
            "base_importance": row.base_importance,
            "current_importance": row.current_importance,
        }
