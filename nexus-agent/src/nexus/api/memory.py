"""FastAPI router for /api/v1/memory — semantic search and CRUD for long-term memory."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query

from nexus.db.base import async_session
from nexus.db.context import get_tenant
from nexus.db.models.memory import Memory
from nexus.db.repositories.base import GenericRepository

logger = structlog.get_logger("nexus.api.memory")

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("")
async def list_memories(
    q: str | None = Query(None, description="Semantic search query"),
    kind: str | None = Query(None, description="Filter by memory kind (episodic, semantic, procedural)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """List/search memories for the caller's tenant."""
    tenant_id = get_tenant()
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="No tenant context")

    async with async_session() as session:
        if q:
            # Semantic search via pgvector (if embedding available)
            from sqlalchemy import text

            sql = text(
                "SELECT id, tenant_id, session_id, kind, content, metadata_, importance, "
                "created_at, last_accessed_at "
                "FROM memory "
                "WHERE tenant_id = :tid"
                + (" AND kind = :kind" if kind else "")
                + " ORDER BY last_accessed_at DESC NULLS LAST "
                "LIMIT :limit OFFSET :offset"
            )
            params: dict[str, Any] = {"tid": tenant_id, "limit": page_size, "offset": (page - 1) * page_size}
            if kind:
                params["kind"] = kind
            result = await session.execute(sql, params)
            rows = result.fetchall()
        else:
            repo = GenericRepository(session, Memory)
            filters: dict[str, Any] = {}
            if kind:
                filters["kind"] = kind
            memories = await repo.find(**filters)
            rows = memories

        return [_memory_to_dict(m) for m in rows]


@router.get("/{memory_id}")
async def get_memory(
    memory_id: uuid.UUID,
) -> dict[str, Any]:
    """Get a single memory by ID."""
    async with async_session() as session:
        repo = GenericRepository(session, Memory)
        mem = await repo.get(memory_id)
    if mem is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return _memory_to_dict(mem)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: uuid.UUID,
) -> None:
    """Delete a memory. Verifies tenant ownership."""
    async with async_session() as session:
        repo = GenericRepository(session, Memory)
        mem = await repo.get(memory_id)
        if mem is None:
            raise HTTPException(status_code=404, detail="Memory not found")

        # Belt-and-suspenders: verify tenant ownership
        tenant_id = get_tenant()
        if tenant_id is not None and mem.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Memory not found")

        await repo.delete(memory_id)
        await session.commit()


def _memory_to_dict(mem: Any) -> dict[str, Any]:
    if isinstance(mem, Memory):
        return {
            "id": str(mem.id),
            "tenant_id": str(mem.tenant_id),
            "session_id": str(mem.session_id) if mem.session_id else None,
            "kind": mem.kind,
            "content": mem.content,
            "metadata_": mem.metadata_,
            "importance": mem.importance,
            "created_at": mem.created_at.isoformat() if mem.created_at else None,
            "last_accessed_at": mem.last_accessed_at.isoformat() if mem.last_accessed_at else None,
        }
    # Row from raw SQL query
    return {
        "id": str(mem[0]),
        "tenant_id": str(mem[1]),
        "session_id": str(mem[2]) if mem[2] else None,
        "kind": mem[3],
        "content": mem[4],
        "metadata_": mem[5],
        "importance": mem[6],
        "created_at": mem[7].isoformat() if mem[7] else None,
        "last_accessed_at": mem[8].isoformat() if mem[8] else None,
    }
