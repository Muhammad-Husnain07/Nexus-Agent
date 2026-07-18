"""Real-time cost dashboard API — per-tenant, per-model, per-day breakdowns."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Query
from sqlalchemy import func, select

from nexus.api.dependencies import SessionDep
from nexus.db.models.agent_run import AgentRun
from nexus.security.rbac import Permission, require_permission

logger = structlog.get_logger("nexus.observability.cost")

router = APIRouter(prefix="/cost", tags=["cost"])


@router.get(
    "/summary",
    dependencies=[require_permission(Permission.AUDIT_READ)],
)
async def cost_summary(
    session: SessionDep,
    tenant_id: Annotated[uuid.UUID | None, Query(description="Filter by tenant")] = None,
    days: Annotated[int, Query(ge=1, le=90, description="Number of days to look back")] = 7,
) -> dict[str, Any]:
    """Return cost summary for the specified period."""
    since = datetime.now(UTC) - timedelta(days=days)

    stmt = select(
        func.sum(AgentRun.total_cost_usd).label("total_cost"),
        func.sum(AgentRun.total_tokens).label("total_tokens"),
        func.count(AgentRun.id).label("total_runs"),
    ).where(AgentRun.started_at >= since)

    if tenant_id is not None:
        stmt = stmt.where(AgentRun.tenant_id == tenant_id)

    result = await session.execute(stmt)
    row = result.one()

    return {
        "period_days": days,
        "tenant_id": str(tenant_id) if tenant_id else "all",
        "total_cost_usd": float(row.total_cost or 0),
        "total_tokens": int(row.total_tokens or 0),
        "total_runs": int(row.total_runs or 0),
    }


@router.get(
    "/daily",
    dependencies=[require_permission(Permission.AUDIT_READ)],
)
async def cost_daily(
    session: SessionDep,
    tenant_id: Annotated[uuid.UUID | None, Query(description="Filter by tenant")] = None,
    days: Annotated[int, Query(ge=1, le=90, description="Number of days")] = 7,
) -> list[dict[str, Any]]:
    """Return per-day cost breakdown."""
    since = datetime.now(UTC) - timedelta(days=days)

    stmt = (
        select(
            func.date_trunc("day", AgentRun.started_at).label("day"),
            func.sum(AgentRun.total_cost_usd).label("cost"),
            func.sum(AgentRun.total_tokens).label("tokens"),
            func.count(AgentRun.id).label("runs"),
        )
        .where(AgentRun.started_at >= since)
        .group_by(func.date_trunc("day", AgentRun.started_at))
        .order_by(func.date_trunc("day", AgentRun.started_at))
    )

    if tenant_id is not None:
        stmt = stmt.where(AgentRun.tenant_id == tenant_id)

    result = await session.execute(stmt)
    rows = result.all()

    return [
        {
            "date": row.day.isoformat() if row.day else None,
            "cost_usd": float(row.cost or 0),
            "tokens": int(row.tokens or 0),
            "runs": int(row.runs or 0),
        }
        for row in rows
    ]


@router.get(
    "/by-tenant",
    dependencies=[require_permission(Permission.ADMIN_ACCESS)],
)
async def cost_by_tenant(
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=90, description="Number of days")] = 7,
) -> list[dict[str, Any]]:
    """Return per-tenant cost breakdown (admin only)."""
    since = datetime.now(UTC) - timedelta(days=days)

    stmt = (
        select(
            AgentRun.tenant_id,
            func.sum(AgentRun.total_cost_usd).label("cost"),
            func.sum(AgentRun.total_tokens).label("tokens"),
            func.count(AgentRun.id).label("runs"),
        )
        .where(AgentRun.started_at >= since)
        .group_by(AgentRun.tenant_id)
        .order_by(func.sum(AgentRun.total_cost_usd).desc())
    )

    result = await session.execute(stmt)
    rows = result.all()

    return [
        {
            "tenant_id": str(row.tenant_id),
            "cost_usd": float(row.cost or 0),
            "tokens": int(row.tokens or 0),
            "runs": int(row.runs or 0),
        }
        for row in rows
    ]
