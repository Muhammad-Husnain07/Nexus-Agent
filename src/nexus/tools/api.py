"""FastAPI router for /api/v1/tools — CRUD, test, and semantic search."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.base import get_session
from nexus.tools.registry import ToolRegistry
from nexus.tools.schemas import ToolCreate, ToolList, ToolRead, ToolSearchResult, ToolUpdate

logger = structlog.get_logger("nexus.tools.api")

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_registry() -> ToolRegistry:
    return ToolRegistry()


RegistryDep = Annotated[ToolRegistry, Depends(get_registry)]


def _stub_tenant_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.post("", response_model=ToolRead, status_code=201)
async def register_tool(
    data: ToolCreate,
    session: SessionDep,
    registry: RegistryDep,
) -> ToolRead:
    return await registry.register(session, _stub_tenant_id(), data)


@router.get("", response_model=ToolList)
async def list_tools(  # noqa: PLR0913
    registry: RegistryDep,
    session: SessionDep,
    tags: str | None = Query(None, description="Comma-separated tag filter"),
    category: str | None = Query(None, description="Category filter"),
    enabled: bool | None = Query(True, description="Filter by enabled state"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> ToolList:
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    return await registry.list(
        session,
        _stub_tenant_id(),
        tags=tag_list,
        category=category,
        enabled=enabled,
        page=page,
        page_size=page_size,
    )


@router.get("/search", response_model=list[ToolSearchResult])
async def search_tools(
    registry: RegistryDep,
    session: SessionDep,
    q: str = Query(..., description="Search query"),
    k: int = Query(10, ge=1, le=50, description="Number of results"),
) -> list[ToolSearchResult]:
    return await registry.search_semantic(session, _stub_tenant_id(), q, k=k)


@router.get("/{tool_id}", response_model=ToolRead)
async def get_tool(
    tool_id: uuid.UUID,
    registry: RegistryDep,
    session: SessionDep,
) -> ToolRead:
    tool = await registry.get(session, _stub_tenant_id(), tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return tool


@router.put("/{tool_id}", response_model=ToolRead)
async def update_tool(
    tool_id: uuid.UUID,
    data: ToolUpdate,
    registry: RegistryDep,
    session: SessionDep,
) -> ToolRead:
    tool = await registry.update(session, _stub_tenant_id(), tool_id, data)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return tool


@router.delete("/{tool_id}", status_code=204)
async def delete_tool(
    tool_id: uuid.UUID,
    registry: RegistryDep,
    session: SessionDep,
) -> None:
    deleted = await registry.deregister(session, _stub_tenant_id(), tool_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tool not found")


@router.post("/{tool_id}/test", response_model=dict[str, Any])
async def test_tool(
    tool_id: uuid.UUID,
    registry: RegistryDep,
    session: SessionDep,
    sample_input: dict[str, Any] | None = None,  # noqa: PT028
) -> dict[str, Any]:
    tool = await registry.get(session, _stub_tenant_id(), tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")

    payload = sample_input or {}
    if tool.input_schema:
        required = tool.input_schema.get("required", [])
        for field in required:
            if field not in payload:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required field: {field}",
                )

    return {
        "tool": tool.name,
        "endpoint": tool.endpoint_url,
        "method": tool.http_method,
        "input_validated": True,
        "mock_output": tool.output_schema or {"type": "object", "properties": {}},
    }
