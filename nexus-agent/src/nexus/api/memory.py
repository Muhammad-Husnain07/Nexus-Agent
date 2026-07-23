"""FastAPI router for /api/v1/memory — semantic search and CRUD for long-term memory."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query

from nexus.db.base import async_session
from nexus.db.models.memory import Memory
from nexus.db.repositories.base import GenericRepository

logger = structlog.get_logger("nexus.api.memory")

router = APIRouter(prefix="/memory", tags=["memory"])

# Map canonical kind values to legacy kinds still in the DB
KIND_LEGACY_MAP: dict[str, list[str]] = {
    "episodic": [],
    "semantic": ["fact", "preference"],
    "procedural": ["procedure", "decision"],
}


def _expand_kind(kind: str) -> list[str]:
    """Expand canonical kind to include legacy DB values."""
    kinds = [kind]
    kinds.extend(KIND_LEGACY_MAP.get(kind, []))
    return kinds


@router.get("")
async def list_memories(
    q: str | None = Query(None, description="Semantic search query"),
    kind: str | None = Query(None, description="Filter by memory kind"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """List/search memories."""
    from sqlalchemy import text

    kind_list = _expand_kind(kind) if kind else None
    async with async_session() as session:
        where_clause = ""
        params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
        if kind_list:
            placeholders = ", ".join(f":k{i}" for i in range(len(kind_list)))
            where_clause = f" WHERE kind IN ({placeholders})"
            for i, k in enumerate(kind_list):
                params[f"k{i}"] = k

        sql = text(
            "SELECT id, session_id, kind, content, metadata_, importance, "
            "created_at, last_accessed_at "
            "FROM memory"
            + where_clause
            + " ORDER BY last_accessed_at DESC NULLS LAST "
            "LIMIT :limit OFFSET :offset"
        )
        result = await session.execute(sql, params)
        rows = result.fetchall()

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
    """Delete a memory."""
    async with async_session() as session:
        repo = GenericRepository(session, Memory)
        mem = await repo.get(memory_id)
        if mem is None:
            raise HTTPException(status_code=404, detail="Memory not found")

        await repo.delete(memory_id)
        await session.commit()


_REVERSE_KIND_MAP: dict[str, str] = {}
for canonical, legacy in KIND_LEGACY_MAP.items():
    for lk in legacy:
        _REVERSE_KIND_MAP[lk] = canonical


def _normalize_kind(kind: str) -> str:
    """Map legacy kind values to canonical ones."""
    return _REVERSE_KIND_MAP.get(kind, kind)


def _memory_to_dict(mem: Any) -> dict[str, Any]:
    if isinstance(mem, Memory):
        return {
            "id": str(mem.id),
            "session_id": str(mem.session_id) if mem.session_id else None,
            "kind": _normalize_kind(mem.kind),
            "content": mem.content,
            "metadata_": mem.metadata_,
            "importance": mem.importance,
            "created_at": mem.created_at.isoformat() if mem.created_at else None,
            "last_accessed_at": mem.last_accessed_at.isoformat() if mem.last_accessed_at else None,
        }
    # Row from raw SQL query
    return {
        "id": str(mem.id),
        "session_id": str(mem.session_id) if mem.session_id else None,
        "kind": _normalize_kind(mem.kind),
        "content": mem.content,
        "metadata_": mem.metadata_,
        "importance": mem.importance,
        "created_at": mem.created_at.isoformat() if mem.created_at else None,
        "last_accessed_at": mem.last_accessed_at.isoformat() if mem.last_accessed_at else None,
    }
