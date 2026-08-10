"""FastAPI router for /api/v1/memory — semantic search and CRUD for long-term memory."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request

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
    request: Request,
    q: str | None = Query(None, description="Semantic search query"),
    kind: str | None = Query(None, description="Filter by memory kind"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """List/search memories.

    C3/P0-C: only memories of the caller's sessions (plus legacy
    NULL-session/system rows) are visible.
    """
    from sqlalchemy import text

    from nexus.security.ownership import accessible_session_ids  # noqa: PLC0415

    owned_ids = await accessible_session_ids(request)
    kind_list = _expand_kind(kind) if kind else None
    async with async_session() as session:
        where_clause = ""
        params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
        if owned_ids:
            placeholders = ", ".join(f":sid{i}" for i in range(len(owned_ids)))
            where_clause = f" WHERE (session_id IN ({placeholders}) OR session_id IS NULL)"
            for i, sid in enumerate(owned_ids):
                params[f"sid{i}"] = sid
        if kind_list:
            kind_placeholders = ", ".join(f":k{i}" for i in range(len(kind_list)))
            where_clause += (
                (" AND " if where_clause else " WHERE ")
                + f"kind IN ({kind_placeholders})"
            )
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


async def _require_memory_access(request: Request, mem: Any) -> None:
    """C3/P0-C: a memory row is accessible through its session only."""
    from nexus.security.ownership import require_session_access  # noqa: PLC0415

    if mem is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    if getattr(mem, "session_id", None) is not None:
        await require_session_access(request, mem.session_id)


@router.get("/{memory_id}")
async def get_memory(
    memory_id: uuid.UUID,
    request: Request,
) -> dict[str, Any]:
    """Get a single memory by ID (owner-scoped)."""
    async with async_session() as session:
        repo = GenericRepository(session, Memory)
        mem = await repo.get(memory_id)
    await _require_memory_access(request, mem)
    return _memory_to_dict(mem)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: uuid.UUID,
    request: Request,
) -> None:
    """Delete a memory (owner-scoped)."""
    async with async_session() as session:
        repo = GenericRepository(session, Memory)
        mem = await repo.get(memory_id)
        await _require_memory_access(request, mem)

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
