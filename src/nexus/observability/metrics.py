"""Prometheus-compatible metrics via prometheus-client.

Exposes counters, histograms, and gauges for agent runs, tool calls,
LLM tokens, cost, active sessions, and HITL approvals.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

router = APIRouter(tags=["metrics"])


agent_runs_total = Counter(
    "agent_runs_total",
    "Total number of agent runs",
    ["tenant", "status"],
)

agent_run_duration_seconds = Histogram(
    "agent_run_duration_seconds",
    "Duration of agent runs in seconds",
    ["tenant"],
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)

tool_calls_total = Counter(
    "tool_calls_total",
    "Total number of tool calls",
    ["tenant", "tool", "status"],
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed",
    ["tenant", "provider", "direction"],
)

llm_cost_usd_total = Counter(
    "llm_cost_usd_total",
    "Total LLM cost in USD",
    ["tenant"],
)

active_sessions = Gauge(
    "active_sessions",
    "Number of currently active sessions",
    ["tenant"],
)

hitl_approvals_pending = Gauge(
    "hitl_approvals_pending",
    "Number of pending HITL approvals",
    ["tenant"],
)


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus scrape endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
