"""Circuit-breaker registry for tool providers.

Provides a per-provider (keyed by provider/tool name) circuit breaker that
the ToolExecutor consults BEFORE making an HTTP call. Thresholds come from
the provider metadata (``circuit_breaker_threshold``) with settings fallback.
In-memory per-process; Redis-backed distributed breakers can be added later
behind the same interface.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.errors.resilience import CircuitBreaker, CircuitOpenError

logger = structlog.get_logger("nexus.tools.circuit_breaker")

_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(name: str, failure_threshold: int = 5, cooldown_s: float = 30.0) -> CircuitBreaker:
    """Return (and lazily create) the circuit breaker for a provider."""
    existing = _breakers.get(name)
    if existing is not None:
        return existing
    breaker = CircuitBreaker(
        name=name,
        failure_threshold=max(1, failure_threshold),
        cooldown_seconds=max(1.0, cooldown_s),
    )
    _breakers[name] = breaker
    return breaker


def is_open(name: str) -> bool:
    """True when the provider's circuit is open (call should be rejected)."""
    breaker = _breakers.get(name)
    return breaker is not None and breaker.state.value == "open"


def record_success(name: str) -> None:
    """Record a successful call for a provider."""
    breaker = _breakers.get(name)
    if breaker is not None:
        breaker._on_success()  # noqa: SLF001 — internal state transition


def record_failure(name: str) -> None:
    """Record a failed call for a provider (may trip the breaker)."""
    breaker = _breakers.get(name)
    if breaker is not None:
        breaker._on_failure()  # noqa: SLF001


def breaker_state(name: str) -> str:
    """Return the current breaker state for a provider (for observability)."""
    breaker = _breakers.get(name)
    return breaker.state.value if breaker is not None else "unknown"


def reset_all() -> None:
    """Reset all breakers (tests / operator action)."""
    _breakers.clear()
