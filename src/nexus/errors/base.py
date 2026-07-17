"""NexusError hierarchy, error codes, and ErrorHandlerMiddleware.

Provides a structured error JSON response ``{error:{code, message, request_id}}``
for all unhandled exceptions, with internal details logged via structlog.
"""

from __future__ import annotations

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
    APPROVAL_REJECTED = "APPROVAL_REJECTED"

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


class TenantSuspendedError(NexusError):
    def __init__(self, message: str = "Tenant account is suspended", **kwargs: Any) -> None:
        super().__init__(
            code=ErrorCode.TENANT_SUSPENDED, message=message, status_code=403, **kwargs
        )


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


class ApprovalRejected(AgentError):
    def __init__(self, message: str = "Approval rejected", **kwargs: Any) -> None:
        super().__init__(code=ErrorCode.APPROVAL_REJECTED, message=message, **kwargs)


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
