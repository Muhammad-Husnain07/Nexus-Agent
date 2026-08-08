"""ExecutionStrategy — deterministic *how* layer between planner and executor.

The planner defines WHAT (nodes + dependencies). The strategy translates plan
shape into an execution strategy: sequential chains, parallel fan-out, map
(iterate_over), reduce (aggregates), retry/background/streaming annotations.
Deterministic and metadata-driven — no LLM, no tool-name logic.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExecutionStrategy(str, Enum):
    """One execution strategy for the plan."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    MAP = "map"
    REDUCE = "reduce"
    RETRY = "retry"
    BACKGROUND = "background"
    STREAMING = "streaming"


class StrategyDecision(BaseModel):
    """Typed strategy output consumed by the executor/estimator."""

    model_config = ConfigDict(frozen=True)

    strategy: ExecutionStrategy = Field(description="Dominant strategy")
    reasons: tuple[str, ...] = Field(default_factory=tuple, description="Why (debug/telemetry)")
    background: bool = Field(default=False, description="Run in background (latency-driven)")
    streaming: bool = Field(default=False, description="Emit incremental results")


def select_strategy(
    nodes: list[dict[str, Any]],
    waves: list[list[str]] | None = None,
    estimated_latency_ms: float | None = None,
    background_threshold_ms: float | None = None,
) -> StrategyDecision:
    """Select the execution strategy from plan shape (deterministic).

    Signals (metadata-driven):
    - any ``iterate_over`` → MAP (map over results)
    - any reduce/aggregate node → REDUCE
    - >1 wave → SEQUENTIAL (dependency chain)
    - 1 wave with >1 node → PARALLEL (independent fan-out)
    - otherwise → SEQUENTIAL (single step)
    - ``estimated_latency_ms >= background_threshold_ms`` → background=True
    """
    reasons: list[str] = []

    has_map = any(bool(n.get("iterate_over")) for n in nodes)
    has_reduce = any(
        str(n.get("kind") or "") in ("reduce", "aggregate") or n.get("aggregate")
        for n in nodes
    )

    if has_map:
        strategy = ExecutionStrategy.MAP
        reasons.append("iterate_over present")
        if has_reduce:
            strategy = ExecutionStrategy.REDUCE
            reasons.append("aggregate present")
    elif has_reduce:
        strategy = ExecutionStrategy.REDUCE
        reasons.append("aggregate present")
    elif waves and len(waves) > 1:
        strategy = ExecutionStrategy.SEQUENTIAL
        reasons.append(f"{len(waves)} dependency waves")
    elif waves and len(waves[0]) > 1:
        strategy = ExecutionStrategy.PARALLEL
        reasons.append(f"{len(waves[0])} independent nodes")
    else:
        strategy = ExecutionStrategy.SEQUENTIAL
        reasons.append("single step")

    background = False
    if background_threshold_ms is not None and estimated_latency_ms is not None:
        if estimated_latency_ms >= background_threshold_ms:
            background = True
            reasons.append(f"latency {estimated_latency_ms:.0f}ms >= {background_threshold_ms:.0f}ms")

    return StrategyDecision(
        strategy=strategy,
        reasons=tuple(reasons),
        background=background,
    )
