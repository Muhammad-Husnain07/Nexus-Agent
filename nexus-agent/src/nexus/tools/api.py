"""FastAPI router for /api/v1/tools — CRUD, test, and semantic search."""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from nexus.api.depends import TenantDep
from nexus.db.base import get_session

from nexus.tools.registry import ToolRegistry
from nexus.tools.result import ToolResult
from nexus.tools.schemas import ToolCreate, ToolList, ToolRead, ToolSearchResult, ToolUpdate

logger = structlog.get_logger("nexus.tools.api")

router = APIRouter(prefix="/tools", tags=["tools"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_registry() -> ToolRegistry:
    return ToolRegistry()


RegistryDep = Annotated[ToolRegistry, Depends(get_registry)]


@router.post(
    "",
    response_model=ToolRead,
    status_code=201,
)
async def register_tool(
    session: SessionDep,
    registry: RegistryDep,
    tenant_id: TenantDep,
    request: Request,
) -> ToolRead:
    tool_data = await request.json()
    tool = ToolCreate(**tool_data)
    return await registry.register(session, tenant_id, tool)


@router.get("", response_model=ToolList)
async def list_tools(  # noqa: PLR0913
    registry: RegistryDep,
    session: SessionDep,
    tenant_id: TenantDep,
    tags: str | None = Query(None, description="Comma-separated tag filter"),
    category: str | None = Query(None, description="Category filter"),
    enabled: bool | None = Query(True, description="Filter by enabled state"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> ToolList:
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    return await registry.list(
        session,
        tenant_id,
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
    tenant_id: TenantDep,
    q: str = Query(..., description="Search query"),
    k: int = Query(10, ge=1, le=50, description="Number of results"),
) -> list[ToolSearchResult]:
    return await registry.search_semantic(session, tenant_id, q, k=k)


@router.get("/{tool_id}", response_model=ToolRead)
async def get_tool(
    tool_id: uuid.UUID,
    registry: RegistryDep,
    session: SessionDep,
    tenant_id: TenantDep,
) -> ToolRead:
    tool = await registry.get(session, tenant_id, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return tool


@router.put(
    "/{tool_id}",
    response_model=ToolRead,
)
async def update_tool(
    tool_id: uuid.UUID,
    data: ToolUpdate,
    registry: RegistryDep,
    session: SessionDep,
    tenant_id: TenantDep,
) -> ToolRead:
    tool = await registry.update(session, tenant_id, tool_id, data)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return tool


@router.delete(
    "/{tool_id}",
    status_code=204,
)
async def delete_tool(
    tool_id: uuid.UUID,
    registry: RegistryDep,
    session: SessionDep,
    tenant_id: TenantDep,
) -> None:
    deleted = await registry.deregister(session, tenant_id, tool_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tool not found")


@router.post("/{tool_id}/test", response_model=ToolResult)
async def test_tool(  # noqa: PLR0913
    tool_id: uuid.UUID,
    registry: RegistryDep,
    session: SessionDep,
    tenant_id: TenantDep,
    sample_input: dict[str, Any] | None = None,  # noqa: PT028
    dry_run: bool = Query(True, description="If True, validate schema only without HTTP call"),  # noqa: PT028
) -> ToolResult:
    tool = await registry.get(session, tenant_id, tool_id)
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

    if dry_run:
        logger.info(
            "tool.test_dry_run",
            tool=tool.name,
            endpoint=tool.endpoint_url,
            method=tool.http_method,
        )
        return ToolResult(
            tool_id=tool.id,
            tool_name=tool.name,
            status="success",
            data={"dry_run": True, "message": "Schema validation passed"},
            duration_ms=0,
        )

    logger.info(
        "tool.test_executing",
        tool=tool.name,
        endpoint=tool.endpoint_url,
        method=tool.http_method,
        input_size=len(json.dumps(payload)),
    )

    result = await registry.test_http_connection(tool, sample_input=payload)

    logger.info(
        "tool.test_completed",
        tool=tool.name,
        status=result.status,
        http_status=result.http_status,
        duration_ms=result.duration_ms,
    )
    return result


@router.get("/{tool_id}/versions/diff")
async def diff_tool_versions(
    tool_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    from_version: int = Query(..., ge=1, description="Source version number"),
    to_version: int = Query(..., ge=1, description="Target version number"),
) -> dict[str, Any]:
    """Compare two versions of a tool definition."""
    from sqlalchemy import select as sa_select

    from nexus.db.models.tool_version import ToolVersion
    from nexus.tools.schemas import ToolVersionDiff

    stmt = sa_select(ToolVersion).where(
        ToolVersion.tool_id == tool_id,
        ToolVersion.tenant_id == tenant_id,
        ToolVersion.version.in_([from_version, to_version]),
    )
    result = await session.execute(stmt)
    versions = {v.version: v for v in result.scalars().all()}

    if from_version not in versions or to_version not in versions:
        raise HTTPException(status_code=404, detail="One or both versions not found")

    old_snapshot = versions[from_version].snapshot or {}
    new_snapshot = versions[to_version].snapshot or {}

    changed_fields: list[str] = []
    all_keys = set(old_snapshot.keys()) | set(new_snapshot.keys())
    for key in sorted(all_keys):
        if old_snapshot.get(key) != new_snapshot.get(key):
            changed_fields.append(key)

    return ToolVersionDiff(
        tool_id=tool_id,
        old_version=from_version,
        new_version=to_version,
        changed_fields=changed_fields,
    ).model_dump(mode="json")
