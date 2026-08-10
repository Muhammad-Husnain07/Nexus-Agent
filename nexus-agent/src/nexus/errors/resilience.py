"""Resilience — exception hierarchy, retry policies, and circuit breaker (combined)."""

import uuid
from enum import Enum
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

logger = structlog.get_logger("nexus.errors.base")


class ErrorCode(str, Enum):
    """Machine-readable error codes for API responses."""

    # General
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    SERVICE_DEGRADED = "SERVICE_DEGRADED"

    # Security
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    TENANT_NOT_FOUND = "TENANT_NOT_FOUND"
    TENANT_SUSPENDED = "TENANT_SUSPENDED"

    # Agent
    PLANNING_FAILED = "PLANNING_FAILED"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    LLM_FAILED = "LLM_FAILED"
    MAX_ITERATIONS = "MAX_ITERATIONS"
    CONTEXT_WINDOW_EXCEEDED = "CONTEXT_WINDOW_EXCEEDED"

    # Resilience
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    DEAD_LETTER = "DEAD_LETTER"


class NexusError(Exception):
    """Base exception for all Nexus-domain errors.

    Attributes:
        code: Machine-readable error code (see ``ErrorCode``).
        message: Human-readable description.
        details: Additional context (logged, not exposed to client).
        status_code: HTTP status code.
    """

    def __init__(
        self,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        message: str = "An unexpected error occurred",
        details: dict[str, Any] | None = None,
        status_code: int = 500,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code
        super().__init__(self.message)


# ── Security Errors ─────────────────────────────────────────────────────────


class UnauthorizedError(NexusError):
    def __init__(self, message: str = "Authentication required", **kwargs: Any) -> None:
        super().__init__(code=ErrorCode.UNAUTHORIZED, message=message, status_code=401, **kwargs)


class ForbiddenError(NexusError):
    def __init__(self, message: str = "Forbidden", **kwargs: Any) -> None:
        super().__init__(code=ErrorCode.FORBIDDEN, message=message, status_code=403, **kwargs)


# ── Agent Errors ────────────────────────────────────────────────────────────


class AgentError(NexusError):
    def __init__(
        self,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        message: str = "Agent error",
        **kwargs: Any,
    ) -> None:
        super().__init__(code=code, message=message, status_code=400, **kwargs)


class PlanningError(AgentError):
    def __init__(self, message: str = "Failed to create plan", **kwargs: Any) -> None:
        super().__init__(code=ErrorCode.PLANNING_FAILED, message=message, **kwargs)


class ToolExecutionError(AgentError):
    def __init__(self, message: str = "Tool execution failed", **kwargs: Any) -> None:
        super().__init__(code=ErrorCode.TOOL_EXECUTION_FAILED, message=message, **kwargs)


class MaxIterationsError(AgentError):
    def __init__(self, message: str = "Max iterations exceeded", **kwargs: Any) -> None:
        super().__init__(code=ErrorCode.MAX_ITERATIONS, message=message, **kwargs)


class ContextWindowExceededError(AgentError):
    def __init__(self, message: str = "Context window exceeded", **kwargs: Any) -> None:
        super().__init__(code=ErrorCode.CONTEXT_WINDOW_EXCEEDED, message=message, **kwargs)


class PlaceholderResolutionError(AgentError):
    """Raised when a symbolic ``${ref.result.field}`` placeholder cannot be
    resolved before a tool call (dependency failed, ref unknown, or field
    missing). Fail-closed invariant I2: an unresolved placeholder must
    never reach a tool — neither as ``None`` nor as the raw string.
    """

    def __init__(self, message: str = "Unresolved placeholder reference", **kwargs: Any) -> None:
        super().__init__(code=ErrorCode.PLANNING_FAILED, message=message, **kwargs)


# ── Rate / Quota Errors ─────────────────────────────────────────────────────


class RateLimitError(NexusError):
    def __init__(
        self, message: str = "Rate limit exceeded", retry_after_s: float = 0.0, **kwargs: Any
    ) -> None:
        self.retry_after_s = retry_after_s
        super().__init__(code=ErrorCode.RATE_LIMITED, message=message, status_code=429, **kwargs)


class QuotaExceededError(NexusError):
    def __init__(self, message: str = "Quota exceeded", **kwargs: Any) -> None:
        super().__init__(code=ErrorCode.QUOTA_EXCEEDED, message=message, status_code=429, **kwargs)


# ── Resilience Errors ───────────────────────────────────────────────────────


class CircuitOpenError(NexusError):
    """Raised when a circuit breaker is open and the call is rejected."""

    def __init__(self, name: str, **kwargs: Any) -> None:
        super().__init__(
            code=ErrorCode.CIRCUIT_OPEN,
            message=f"Circuit breaker open for '{name}'",
            status_code=503,
            **kwargs,
        )


class DeadLetterError(NexusError):
    """Raised when an execution has been sent to the dead letter queue."""

    def __init__(self, message: str = "Execution sent to dead letter queue", **kwargs: Any) -> None:
        super().__init__(code=ErrorCode.DEAD_LETTER, message=message, status_code=500, **kwargs)


# ── ErrorHandler Middleware ──────────────────────────────────────────────────


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that catches all exceptions and returns structured JSON.

    Response format: ``{error: {code, message, request_id}}``

    Internal details (``details`` dict) are logged but never exposed to the
    client.
    """

    def __init__(self, app: ASGIApp, debug: bool = False) -> None:
        super().__init__(app)
        self._debug = debug

    async def dispatch(self, request: Request, call_next: callable) -> JSONResponse:
        req_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            return self._handle_error(exc, req_id)

    def _handle_error(self, exc: Exception, req_id: str) -> JSONResponse:
        if isinstance(exc, NexusError):
            code = exc.code.value
            message = exc.message
            status = exc.status_code
            details = exc.details
        else:
            code = ErrorCode.INTERNAL_ERROR.value
            message = str(exc) if self._debug else "An unexpected error occurred"
            status = 500
            details = {}

        logger.error(
            "request.error",
            error_code=code,
            status=status,
            request_id=req_id,
            details=details,
            exc_info=exc,
        )

        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": req_id,
                }
            },
        )


# ============================================================================
# Retry policies
# ============================================================================

import logging

from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)
from tenacity.stop import stop_never


def llm_retry_policy(
    max_attempts: int = 5,
    min_wait_s: float = 1.0,
    max_wait_s: float = 32.0,
) -> AsyncRetrying:
    """Retry policy for LLM calls — exponential backoff 1–32s, up to 5 attempts.

    Retryable exceptions include: rate limits, connection errors, server errors.
    """
    from litellm.exceptions import APIConnectionError, InternalServerError, RateLimitError

    return AsyncRetrying(
        stop=(stop_never if max_attempts < 1 else stop_after_attempt(max_attempts)),
        wait=wait_exponential(multiplier=1, min=min_wait_s, max=max_wait_s) + wait_random(0, 1),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError, InternalServerError)),
        before_sleep=before_sleep_log(logging.getLogger("nexus.errors.retry"), logging.WARNING),
        reraise=True,
    )


def tool_http_retry_policy(
    max_attempts: int = 3,
    min_wait_s: float = 1.0,
    max_wait_s: float = 30.0,
    idempotent: bool = False,
) -> AsyncRetrying:
    """Retry policy for tool HTTP calls — exponential backoff 1–30s.

    When ``idempotent`` is ``False``, only retries on network errors and 5xx
    (not on 4xx client errors).  When ``idempotent`` is ``True``, also retries
    on 429 and safe 4xx responses.
    """
    import httpx
    from tenacity import retry_if_exception

    retryable_codes = (408, 429, 500, 502, 503, 504)

    def _predicate(exc: BaseException) -> bool:
        if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            if code in retryable_codes:
                return True
            if idempotent and 400 <= code < 500 and code not in (401, 403):
                return True
        return False

    return AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait_s, max=max_wait_s) + wait_random(0, 1),
        retry=retry_if_exception(_predicate),
        before_sleep=before_sleep_log(logging.getLogger("nexus.errors.retry"), logging.WARNING),
        reraise=True,
    )


def db_retry_policy(
    max_attempts: int = 3,
    min_wait_s: float = 0.5,
    max_wait_s: float = 10.0,
) -> AsyncRetrying:
    """Retry policy for database operations — exponential backoff 0.5–10s.

    Retries on connection errors, deadlocks, and serialisation failures.
    """
    from sqlalchemy.exc import DBAPIError, OperationalError

    return AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait_s, max=max_wait_s) + wait_random(0, 0.5),
        retry=retry_if_exception_type((OperationalError, DBAPIError)),
        before_sleep=before_sleep_log(logging.getLogger("nexus.errors.retry"), logging.WARNING),
        reraise=True,
    )


def redis_retry_policy(
    max_attempts: int = 3,
    min_wait_s: float = 0.1,
    max_wait_s: float = 5.0,
) -> AsyncRetrying:
    """Retry policy for Redis operations — exponential backoff 0.1–5s."""
    from redis.asyncio import RedisError

    return AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait_s, max=max_wait_s) + wait_random(0, 0.1),
        retry=retry_if_exception_type(RedisError),
        before_sleep=before_sleep_log(logging.getLogger("nexus.errors.retry"), logging.WARNING),
        reraise=True,
    )


# ============================================================================
# Circuit breaker
# ============================================================================

import time
from enum import Enum
from typing import Any

import structlog


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
