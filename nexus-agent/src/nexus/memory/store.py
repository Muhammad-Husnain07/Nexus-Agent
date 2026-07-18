"""Long-term memory store backed by the ``Memory`` SQLAlchemy model with pgvector.

Provides a typed ``MemoryStore`` for persisting and retrieving memories
(user preferences, facts, procedures, episodic summaries) via semantic
search.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from sqlalchemy import text

from nexus.db.base import async_session
from nexus.db.models.memory import Memory
from nexus.db.repositories.base import TenantScopedRepository

logger = structlog.get_logger("nexus.memory.store")

MemoryKind = Literal["episodic", "semantic", "procedural", "preference"]


class MemoryStore:
    """Postgres-backed memory store with vector similarity search.

    Namespace convention: ``(tenant_id, "memories", memory_kind)``.

    All methods operate within the ``Memory`` table which has a ``VECTOR(n)``
    column for embeddings (dimension configured via ``embedding_dimensions``)
    and an ``ivfflat`` index for approximate nearest neighbour search.
    """

    def __init__(self) -> None:
        pass

    async def put(  # noqa: PLR0913
        self,
        namespace: tuple[str, str, str],
        memory_id: uuid.UUID | None = None,
        content: str = "",
        embedding: list[float] | None = None,
        metadata: dict[str, Any] | None = None,
        importance: float = 0.5,
    ) -> uuid.UUID:
        """Store a memory entry.

        Args:
            namespace: ``(tenant_id, "memories", memory_kind)``.
            memory_id: Optional UUID (auto-generated if ``None``).
            content: The memory text.
            embedding: Vector of dimension ``embedding_dimensions`` for semantic search.
            metadata: Arbitrary JSON-serialisable metadata.
            importance: Salience score 0-1.

        Returns:
            The UUID of the stored memory.
        """
        tenant_id, _, kind = namespace
        mid = memory_id or uuid.uuid4()

        async with async_session() as session:
            repo = TenantScopedRepository(session, Memory)
            existing = await repo.get(mid)
            if existing is not None:
                existing.content = content
                existing.importance = importance
                existing.metadata_ = metadata or {}
                existing.last_accessed_at = datetime.now(UTC)
                if embedding is not None:
                    existing.embedding = embedding
            else:
                await repo.create(
                    id=mid,
                    tenant_id=uuid.UUID(tenant_id),
                    kind=kind,
                    content=content,
                    embedding=embedding,
                    metadata_=metadata or {},
                    importance=importance,
                )
            await session.commit()
        return mid

    async def get(
        self, namespace: tuple[str, str, str], memory_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """Retrieve a single memory by ID.

        Returns:
            A dict representation or ``None`` if not found.
        """
        async with async_session() as session:
            repo = TenantScopedRepository(session, Memory)
            mem = await repo.get(memory_id)
            if mem is None:
                return None
            # Update last_accessed_at
            mem.last_accessed_at = datetime.now(UTC)
            await session.commit()
            return self._row_to_dict(mem)

    async def search(
        self,
        query_embedding: list[float],
        namespace: tuple[str, str, str] | None = None,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search over stored memories.

        Uses cosine similarity via pgvector's ``<=>`` operator on the
        ``embedding`` column.  Results are ordered by similarity descending.

        Args:
            query_embedding: Query vector of dimension ``embedding_dimensions``.
            namespace: Optional ``(tenant_id, "memories", kind)`` filter.
            top_k: Max results.
            metadata_filter: Optional JSONB key-value filter.

        Returns:
            List of matching memory dicts with ``similarity`` key added.
        """
        vec_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"
        sql = "SELECT id, tenant_id, session_id, kind, content, metadata_, importance, "
        sql += "created_at, last_accessed_at, "
        sql += f"1 - (embedding <=> '{vec_literal}'::vector) AS similarity "
        sql += "FROM memory WHERE 1=1 "
        params: dict[str, Any] = {}

        if namespace is not None:
            tenant_id, _, kind = namespace
            sql += "AND tenant_id = :tenant_id "
            params["tenant_id"] = tenant_id
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
                "tenant_id": str(row[1]),
                "session_id": str(row[2]) if row[2] else None,
                "kind": row[3],
                "content": row[4],
                "metadata": row[5],
                "importance": float(row[6]),
                "created_at": str(row[7]) if row[7] else None,
                "last_accessed_at": str(row[8]) if row[8] else None,
                "similarity": float(row[9]),
            }
            output.append(d)
        return output

    async def delete(self, namespace: tuple[str, str, str], memory_id: uuid.UUID) -> bool:
        """Delete a memory by ID.

        Returns:
            ``True`` if deleted, ``False`` if not found.
        """
        async with async_session() as session:
            repo = TenantScopedRepository(session, Memory)
            deleted = await repo.delete(memory_id)
            if deleted:
                await session.commit()
            return deleted

    @staticmethod
    def _row_to_dict(row: Memory) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "session_id": str(row.session_id) if row.session_id else None,
            "kind": row.kind,
            "content": row.content,
            "metadata": row.metadata_,
            "importance": row.importance,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "last_accessed_at": row.last_accessed_at.isoformat() if row.last_accessed_at else None,
        }
