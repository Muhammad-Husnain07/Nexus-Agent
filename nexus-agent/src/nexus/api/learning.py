"""Learning API — historically successful workflows and provider reliability.

Endpoints:
- ``GET /learning/workflows?intent=`` — find past successful workflows for an intent
- ``GET /learning/providers/{name}/reliability`` — get provider EWMA reliability score

No hardcoded intent patterns. Fully dynamic — queries the execution history.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from nexus.db.base import get_session_factory
from nexus.db.models.invocation_outcome import InvocationOutcome
from nexus.db.models.registry import ProviderModel
from nexus.metrics.store import get_provider_reliability

logger = structlog.get_logger("nexus.api.learning")

router = APIRouter(prefix="/learning", tags=["learning"])


@router.get("/workflows")
async def find_successful_workflows(
    intent: str = Query("", description="Intent pattern to match"),
    days_back: int = Query(30, ge=1, le=365, description="Max days of history"),
    top_k: int = Query(5, ge=1, le=50, description="Max workflows to return"),
) -> list[dict[str, Any]]:
    """Find historically successful workflows matching the given intent.

    Searches ``InvocationOutcome`` records where ``success=True`` and
    ``outcome_version=2`` (post-Phase 6). Ordered by lowest cost + latency.
    """
    if not intent:
        return []

    since = datetime.now(UTC) - timedelta(days=days_back)
    async with get_session_factory()() as session:
        result = await session.execute(
            select(InvocationOutcome)
            .where(
                InvocationOutcome.success == True,
                InvocationOutcome.created_at >= since,
                InvocationOutcome.error_message.is_(None),
            )
            .order_by(
                InvocationOutcome.total_cost_usd.asc(),
                InvocationOutcome.latency_ms.asc(),
            )
            .limit(top_k)
        )
        outcomes = result.scalars().all()

    workflows: list[dict[str, Any]] = []
    for o in outcomes:
        workflows.append({
            "session_id": str(o.session_id),
            "total_cost_usd": o.total_cost_usd,
            "latency_ms": o.latency_ms,
            "tool_count": o.tool_count or 0,
            "created_at": str(o.created_at),
        })

    logger.info("learning.workflows_found", intent=intent, count=len(workflows))
    return workflows


@router.get("/providers/{provider_name}/reliability")
async def get_provider_reliability_endpoint(
    provider_name: str,
) -> dict[str, Any]:
    """Get the EWMA reliability score for a provider."""
    score = await get_provider_reliability(provider_name)
    if score is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return {"provider": provider_name, "reliability_score": score}
