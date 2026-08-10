"""ReasoningBudget — the first-class per-invocation reasoning contract (P0).

Every subsystem (planner, validator, compiler, recovery, executor) draws
from ONE budget; nothing runs with an independent unbounded counter. The
budget enforces reserve-before-execute semantics: a component reserves
budget BEFORE starting a potentially blocking operation, so concurrent
nodes cannot collectively overspend the invocation.

The SAME budget unifies the previously-independent replan loops (validator
repairs, compile retries, recovery replans) — an identical failure can
never trigger an identical replan indefinitely.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasoningBudget:
    """Immutable limits + a consumed ledger for one invocation."""

    max_wall_time_ms: float = 120_000.0
    max_graph_steps: int = 50
    max_replans: int = 4
    max_recovery_attempts: int = 3
    max_llm_calls: int = 30
    max_tool_calls: int = 40
    max_cost_usd: float = 1.0
    started_at: float = field(default_factory=time.perf_counter)
    consumed: dict[str, float] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Reserve-before-execute semantics
    # ------------------------------------------------------------------

    def consume(self, key: str, amount: float = 1.0) -> bool:
        """Reserve ``amount`` of ``key``; False when the budget is spent.

        Components MUST call this BEFORE executing a blocking operation.
        ``amount`` is fractional for ``cost_usd`` (actual USD spend),
        integral for the call-count dimensions.
        """
        limit = getattr(self, f"max_{key}", None)
        if limit is None:
            return True
        used = self.consumed.get(key, 0.0) + amount
        if used > limit:
            return False
        self.consumed[key] = used
        return True

    def settle_cost(self, actual_cost_usd: float) -> None:
        """A1/P1-A: record ACTUAL cost after an LLM/tool call — the
        reserved estimate is corrected, never double-counted."""
        if actual_cost_usd > 0:
            self.consumed["cost_usd"] = (
                self.consumed.get("cost_usd", 0.0) + float(actual_cost_usd)
            )

    def remaining(self, key: str) -> float:
        limit = getattr(self, f"max_{key}", None)
        if limit is None:
            return 1.0
        return max(0.0, limit - self.consumed.get(key, 0.0))

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started_at) * 1000

    def exceeded(self) -> str | None:
        """The first exhausted dimension (or None)."""
        if self.elapsed_ms() > self.max_wall_time_ms:
            return "wall_time"
        for key, limit in (
            ("graph_steps", self.max_graph_steps),
            ("replans", self.max_replans),
            ("recovery", self.max_recovery_attempts),
            ("llm_calls", self.max_llm_calls),
            ("tool_calls", self.max_tool_calls),
            ("cost_usd", self.max_cost_usd),
        ):
            if self.consumed.get(key, 0.0) >= limit:
                return key
        return None

    def merge(self, other: dict[str, Any] | "ReasoningBudget") -> None:
        """A1/P1-A: merge another budget's ledger (the state carrier from a
        node) into this one — the runner's instance sees node consumption.
        The wall-clock stays with the ORIGINAL budget (never restarted)."""
        raw = other.to_dict() if isinstance(other, ReasoningBudget) else other
        if not isinstance(raw, dict):
            return
        for key, value in (raw.get("consumed") or {}).items():
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            self.consumed[key] = max(self.consumed.get(key, 0.0), v)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_wall_time_ms": self.max_wall_time_ms,
            "max_graph_steps": self.max_graph_steps,
            "max_replans": self.max_replans,
            "max_recovery_attempts": self.max_recovery_attempts,
            "max_llm_calls": self.max_llm_calls,
            "max_tool_calls": self.max_tool_calls,
            "max_cost_usd": self.max_cost_usd,
            "_started_at": self.started_at,
            "consumed": dict(self.consumed),
        }


def budget_from_state(state: dict[str, Any]) -> ReasoningBudget:
    """Rebuild the budget from the state carrier (or a fresh default).

    A1/P1-A: ``_started_at`` is serialized so the wall clock SURVIVES the
    state carrier round-trip — node-level rebuilds never restart it.
    """
    raw = state.get("_invocation_budget")
    if isinstance(raw, dict):
        try:
            return ReasoningBudget(
                max_wall_time_ms=float(raw.get("max_wall_time_ms", 120_000)),
                max_graph_steps=int(raw.get("max_graph_steps", 50)),
                max_replans=int(raw.get("max_replans", 4)),
                max_recovery_attempts=int(raw.get("max_recovery_attempts", 3)),
                max_llm_calls=int(raw.get("max_llm_calls", 30)),
                max_tool_calls=int(raw.get("max_tool_calls", 40)),
                max_cost_usd=float(raw.get("max_cost_usd", 1.0)),
                started_at=float(raw.get("_started_at", time.perf_counter())),
                consumed={
                    str(k): float(v)
                    for k, v in dict(raw.get("consumed") or {}).items()
                },
            )
        except Exception:
            return ReasoningBudget()
    return ReasoningBudget()
