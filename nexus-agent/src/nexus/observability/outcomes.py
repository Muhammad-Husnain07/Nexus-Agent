"""Invocation outcome tracking — prompt versions, costs, A/B experiments.

Collects per-invocation telemetry and persists it to PostgreSQL for
analytics. Supports prompt version tracking, cost attribution, and
A/B test result collection.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import UTC, datetime
from typing import Any

import structlog

from nexus.config.settings import get_settings
from nexus.observability.tracing import get_tracer

logger = structlog.get_logger("nexus.observability.outcomes")

OUTCOME_VERSION = 1


@dataclass
class InvocationOutcome:
    """Record of a single agent invocation for analytics and debugging.

    Persisted to the ``invocation_outcomes`` table in PostgreSQL.
    """

    session_id: str
    model: str
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    latency_ms: int = 0
    success: bool = False
    reflection_score: float | None = None
    tool_count: int = 0
    tool_error_count: int = 0
    response_type: str | None = None
    error_message: str | None = None
    prompt_versions: dict[str, str] = field(default_factory=dict)
    cost_breakdown: dict[str, Any] = field(default_factory=dict)
    ab_experiment_id: str | None = None
    ab_variant: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_state(state: dict[str, Any], latency_ms: int, error_message: str | None = None) -> InvocationOutcome:
        """Build an outcome record from AgentState."""
        settings = get_settings()
        model = settings.llm.default_model
        response_type = state.get("response_type", "tool")
        tool_results: list = state.get("tool_results", [])
        tool_count = len(tool_results)
        tool_errors = sum(1 for r in tool_results if r.get("status") != "success") if tool_results else 0
        reflection_score = state.get("reflection_score")
        total_cost = state.get("total_cost_usd", 0.0)
        prompt_versions = state.get("_prompt_versions", {})
        cost_breakdown = state.get("_cost_breakdown", {})

        return InvocationOutcome(
            session_id=state.get("session_id", ""),
            model=model,
            total_cost_usd=total_cost,
            total_tokens=state.get("_total_tokens", 0),
            latency_ms=latency_ms,
            success=error_message is None and not state.get("errors"),
            reflection_score=reflection_score,
            tool_count=tool_count,
            tool_error_count=tool_errors,
            response_type=response_type,
            error_message=error_message,
            prompt_versions=prompt_versions,
            cost_breakdown=cost_breakdown,
        )


async def persist_outcome(outcome: InvocationOutcome) -> None:
    """Persist an invocation outcome to PostgreSQL.

    Runs fire-and-forget — failures are logged but never propagated.
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415
        from nexus.db.base import async_session  # noqa: PLC0415

        data = outcome.to_dict()
        async with async_session() as session:
            await session.execute(
                text(
                    "INSERT INTO invocation_outcomes "
                    "(id, session_id, model, total_cost_usd, total_tokens, latency_ms, "
                    "success, reflection_score, tool_count, tool_error_count, "
                    "response_type, error_message, prompt_versions, cost_breakdown, "
                    "ab_experiment_id, ab_variant, outcome_version) "
                    "VALUES (:id, :session_id, :model, :total_cost_usd, :total_tokens, :latency_ms, "
                    ":success, :reflection_score, :tool_count, :tool_error_count, "
                    ":response_type, :error_message, CAST(:prompt_versions AS JSONB), CAST(:cost_breakdown AS JSONB), "
                    ":ab_experiment_id, :ab_variant, :outcome_version)"
                ),
                {
                    "id": uuid.uuid4(),
                    "session_id": data["session_id"],
                    "model": data["model"],
                    "total_cost_usd": data["total_cost_usd"],
                    "total_tokens": data["total_tokens"],
                    "latency_ms": data["latency_ms"],
                    "success": data["success"],
                    "reflection_score": data["reflection_score"],
                    "tool_count": data["tool_count"],
                    "tool_error_count": data["tool_error_count"],
                    "response_type": data["response_type"],
                    "error_message": data["error_message"],
                    "prompt_versions": json.dumps(data["prompt_versions"]),
                    "cost_breakdown": json.dumps(data["cost_breakdown"]),
                    "ab_experiment_id": data["ab_experiment_id"],
                    "ab_variant": data["ab_variant"],
                    "outcome_version": OUTCOME_VERSION,
                },
            )
            await session.commit()
        logger.info("outcome.persisted", session_id=outcome.session_id)
    except Exception as exc:
        logger.warning("outcome.persist_failed", error=str(exc))
