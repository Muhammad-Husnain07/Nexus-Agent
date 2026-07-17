"""Circuit breaker — per-tool and per-LLM-provider failure protection.

State machine: CLOSED → OPEN (after N failures) → HALF_OPEN (after cooldown)
→ CLOSED (on probe success) or OPEN (on probe failure).  State may be
backed by Redis for distributed resilience.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

import structlog

from nexus.errors.base import CircuitOpenError

logger = structlog.get_logger("nexus.errors.circuit_breaker")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """State machine protecting a single resource (tool, LLM provider).

    Thread-safe in-memory implementation.  For distributed resilience,
    use ``RedisCircuitBreaker``.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self.name = name
        self._failure_threshold = failure_threshold
        self._success_threshold = success_threshold
        self._cooldown_seconds = cooldown_seconds

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        return self._state

    async def call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute *func* if the circuit is closed, raising ``CircuitOpenError`` otherwise.

        On success: transition HALF_OPEN→CLOSED when success threshold met.
        On failure: increment count; transition CLOSED→OPEN when threshold met.
        """
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self._cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                logger.info("cb.half_open", name=self.name)
            else:
                raise CircuitOpenError(self.name)

        try:
            result = await func(*args, **kwargs) if _is_async(func) else func(*args, **kwargs)
        except Exception as exc:
            self._on_failure()
            raise exc

        self._on_success()
        return result

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        logger.warning("cb.failure", name=self.name, count=self._failure_count)

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.info("cb.opened", name=self.name)
        elif self._state == CircuitState.CLOSED and self._failure_count >= self._failure_threshold:
            self._state = CircuitState.OPEN
            logger.info("cb.opened", name=self.name, threshold=self._failure_threshold)

    def _on_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                logger.info("cb.closed", name=self.name)
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        logger.info("cb.reset", name=self.name)


class CircuitBreakerRegistry:
    """Manages circuit breakers keyed by name (tool name / LLM provider)."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, name: str, **kwargs: Any) -> CircuitBreaker:
        """Return the breaker for *name*, creating one if needed."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name=name, **kwargs)
        return self._breakers[name]

    def state_of(self, name: str) -> CircuitState | None:
        """Return the current state of the breaker for *name*, or ``None``."""
        cb = self._breakers.get(name)
        return cb.state if cb is not None else None

    def all_open(self) -> list[str]:
        """List all breaker names currently in the OPEN state."""
        return [n for n, cb in self._breakers.items() if cb.state == CircuitState.OPEN]

    def reset_all(self) -> None:
        for cb in self._breakers.values():
            cb.reset()


# Shared registry — importable by executor and LLM client
registry = CircuitBreakerRegistry()


def _is_async(func: Any) -> bool:
    import asyncio

    return asyncio.iscoroutinefunction(func)
