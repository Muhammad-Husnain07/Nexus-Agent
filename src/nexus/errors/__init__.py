"""Custom exception hierarchy, error handler, retry policies, circuit breaker, idempotency, graceful degradation, and dead letter queue."""

from nexus.errors.base import (
    AgentError,
    ApprovalRejected,
    CircuitOpenError,
    ContextWindowExceededError,
    DeadLetterError,
    ErrorCode,
    ErrorHandlerMiddleware,
    ForbiddenError,
    MaxIterationsError,
    NexusError,
    PlanningError,
    QuotaExceededError,
    RateLimitError,
    TenantSuspendedError,
    ToolExecutionError,
    UnauthorizedError,
)
from nexus.errors.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState
from nexus.errors.dead_letter import DeadLetterExecution, DeadLetterQueue
from nexus.errors.graceful_degradation import DegradationManager
from nexus.errors.idempotency import (
    IdempotencyMiddleware,
    cache_idempotent_response,
    get_idempotent_response,
)
from nexus.errors.retry import (
    db_retry_policy,
    llm_retry_policy,
    redis_retry_policy,
    tool_http_retry_policy,
)

__all__ = [
    # Base
    "NexusError",
    "ErrorCode",
    "ErrorHandlerMiddleware",
    # Security
    "UnauthorizedError",
    "ForbiddenError",
    "TenantSuspendedError",
    # Agent
    "AgentError",
    "PlanningError",
    "ToolExecutionError",
    "MaxIterationsError",
    "ContextWindowExceededError",
    "ApprovalRejected",
    # Rate/Quota
    "RateLimitError",
    "QuotaExceededError",
    # Resilience
    "CircuitOpenError",
    "DeadLetterError",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "CircuitState",
    # Retry
    "llm_retry_policy",
    "tool_http_retry_policy",
    "db_retry_policy",
    "redis_retry_policy",
    # Idempotency
    "IdempotencyMiddleware",
    "cache_idempotent_response",
    "get_idempotent_response",
    # Graceful Degradation
    "DegradationManager",
    # Dead Letter
    "DeadLetterExecution",
    "DeadLetterQueue",
]
