"""Invocation outcome tracking — costs, latency, success/failure."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import UTC, datetime
from typing import Any

import structlog

from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.observability.outcomes")

OUTCOME_VERSION = 2


@dataclass
class InvocationOutcome:
    """Record of a single agent invocation for analytics and debugging."""

    session_id: str
    model: str
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    latency_ms: int = 0
    success: bool = False
    tool_count: int = 0
    tool_error_count: int = 0
    error_message: str | None = None
    cost_breakdown: dict[str, Any] = None
    created_at: str = ""

    def __post_init__(self):
        if self.cost_breakdown is None:
            self.cost_breakdown = {}
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_state(state: dict[str, Any], latency_ms: int, error_message: str | None = None) -> InvocationOutcome:
        """Build an outcome record from AgentState."""
        settings = get_settings()
        model = settings.llm.default_model
        tool_results: list = state.get("tool_results", [])
        tool_count = len(tool_results)
        tool_errors = sum(1 for r in tool_results if r.get("status") != "success") if tool_results else 0
        cost_breakdown = state.get("_cost_breakdown", {})

        return InvocationOutcome(
            session_id=state.get("session_id", ""),
            model=model,
            total_cost_usd=state.get("total_cost_usd", 0.0),
            total_tokens=state.get("_total_tokens", 0),
            latency_ms=latency_ms,
            success=error_message is None and not state.get("errors"),
            tool_count=tool_count,
            tool_error_count=tool_errors,
            error_message=error_message,
            cost_breakdown=cost_breakdown,
        )


async def persist_outcome(outcome: InvocationOutcome) -> None:
    """Persist an invocation outcome to PostgreSQL. Fire-and-forget."""
    try:
        from sqlalchemy import text  # noqa: PLC0415
        from nexus.db.base import async_session  # noqa: PLC0415

        data = outcome.to_dict()
        async with async_session() as session:
            await session.execute(
                text(
                    "INSERT INTO invocation_outcomes "
                    "(id, session_id, model, total_cost_usd, total_tokens, latency_ms, "
                    "success, tool_count, tool_error_count, "
                    "error_message, cost_breakdown, outcome_version) "
                    "VALUES (:id, :session_id, :model, :total_cost_usd, :total_tokens, "
                    ":latency_ms, :success, :tool_count, :tool_error_count, "
                    ":error_message, CAST(:cost_breakdown AS JSONB), :outcome_version)"
                ),
                {
                    "id": uuid.uuid4(),
                    "session_id": data["session_id"],
                    "model": data["model"],
                    "total_cost_usd": data["total_cost_usd"],
                    "total_tokens": data["total_tokens"],
                    "latency_ms": data["latency_ms"],
                    "success": data["success"],
                    "tool_count": data["tool_count"],
                    "tool_error_count": data["tool_error_count"],
                    "error_message": data["error_message"],
                    "cost_breakdown": json.dumps(data["cost_breakdown"]),
                    "outcome_version": OUTCOME_VERSION,
                },
            )
            await session.commit()
        logger.info("outcome.persisted", session_id=outcome.session_id)
    except Exception as exc:
        logger.warning("outcome.persist_failed", error=str(exc))
