"""Custom exception hierarchy, error handler, retry policies, circuit breaker, idempotency, graceful degradation, and dead letter queue."""

from nexus.errors.queue import (
    DeadLetterExecution,
    DeadLetterQueue,
    DegradationManager,
    IdempotencyMiddleware,
    cache_idempotent_response,
    get_idempotent_response,
)
from nexus.errors.resilience import (
    AgentError,
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
    ContextWindowExceededError,
    DeadLetterError,
    ErrorCode,
    ErrorHandlerMiddleware,
    ForbiddenError,
    MaxIterationsError,
    NexusError,
    PlaceholderResolutionError,
    PlanningError,
    QuotaExceededError,
    RateLimitError,
    ToolExecutionError,
    UnauthorizedError,
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
    # Agent
    "AgentError",
    "PlanningError",
    "ToolExecutionError",
    "MaxIterationsError",
    "ContextWindowExceededError",
    "PlaceholderResolutionError",
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
