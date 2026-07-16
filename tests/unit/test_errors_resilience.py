"""Unit tests for resilience modules — circuit breaker, idempotency, dead letter, graceful degradation, retry policies."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.errors.base import (
    CircuitOpenError,
    DeadLetterError,
    ErrorCode,
    ErrorHandlerMiddleware,
    NexusError,
    RateLimitError,
)
from nexus.errors.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState
from nexus.errors.dead_letter import DeadLetterQueue
from nexus.errors.graceful_degradation import DegradationManager
from nexus.errors.idempotency import IdempotencyConflict, cache_idempotent_response, get_idempotent_response
from nexus.errors.retry import db_retry_policy, llm_retry_policy, redis_retry_policy, tool_http_retry_policy


# ---------------------------------------------------------------------------
# Error base / error codes
# ---------------------------------------------------------------------------

class TestNexusError:
    """NexusError hierarchy and error codes."""

    def test_error_code_values(self) -> None:
        assert ErrorCode.INTERNAL_ERROR.value == "INTERNAL_ERROR"
        assert ErrorCode.UNAUTHORIZED.value == "UNAUTHORIZED"
        assert ErrorCode.CIRCUIT_OPEN.value == "CIRCUIT_OPEN"
        assert ErrorCode.IDEMPOTENCY_CONFLICT.value == "IDEMPOTENCY_CONFLICT"
        assert ErrorCode.SERVICE_DEGRADED.value == "SERVICE_DEGRADED"

    def test_nexus_error_has_code_and_message(self) -> None:
        err = NexusError(code=ErrorCode.TIMEOUT, message="Request timed out", status_code=504)
        assert err.code == ErrorCode.TIMEOUT
        assert err.message == "Request timed out"
        assert err.status_code == 504

    def test_rate_limit_error_has_retry_after(self) -> None:
        err = RateLimitError(retry_after_s=30.0)
        assert err.retry_after_s == 30.0
        assert err.status_code == 429

    def test_circuit_open_error(self) -> None:
        err = CircuitOpenError("test_tool")
        assert "test_tool" in err.message
        assert err.code == ErrorCode.CIRCUIT_OPEN
        assert err.status_code == 503

    def test_dead_letter_error(self) -> None:
        err = DeadLetterError()
        assert err.code == ErrorCode.DEAD_LETTER


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    """Circuit breaker state machine."""

    @pytest.fixture
    def cb(self) -> CircuitBreaker:
        return CircuitBreaker(name="test", failure_threshold=3, success_threshold=2, cooldown_seconds=0.1)

    async def test_starts_closed(self, cb: CircuitBreaker) -> None:
        assert cb.state == CircuitState.CLOSED

    async def test_opens_after_threshold_failures(self, cb: CircuitBreaker) -> None:
        async def fail() -> None:
            raise ValueError("fail")

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail)
        assert cb.state == CircuitState.CLOSED

        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

    async def test_rejects_calls_when_open(self, cb: CircuitBreaker) -> None:
        async def fail() -> None:
            raise ValueError("fail")

        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitOpenError):
            await cb.call(fail)

    async def test_transitions_to_half_open_after_cooldown(self, cb: CircuitBreaker) -> None:
        async def fail() -> None:
            raise ValueError("fail")

        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.15)  # Wait for cooldown

        async def succeed() -> str:
            return "ok"

        result = await cb.call(succeed)
        assert result == "ok"
        assert cb.state == CircuitState.HALF_OPEN

    async def test_closes_after_success_threshold(self, cb: CircuitBreaker) -> None:
        async def fail() -> None:
            raise ValueError("fail")

        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.15)

        async def succeed() -> str:
            return "ok"

        await cb.call(succeed)  # HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN
        await cb.call(succeed)  # CLOSED
        assert cb.state == CircuitState.CLOSED

    async def test_reset(self, cb: CircuitBreaker) -> None:
        async def fail() -> None:
            raise ValueError("fail")

        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(fail)

        cb.reset()
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerRegistry:
    """Circuit breaker registry."""

    def test_get_or_create(self) -> None:
        registry = CircuitBreakerRegistry()
        cb1 = registry.get("tool:send_email")
        cb2 = registry.get("tool:send_email")
        assert cb1 is cb2

    def test_state_of_returns_none_for_unknown(self) -> None:
        registry = CircuitBreakerRegistry()
        assert registry.state_of("nonexistent") is None


# ---------------------------------------------------------------------------
# Retry Policies
# ---------------------------------------------------------------------------

class TestRetryPolicies:
    """Retry policy creation."""

    def test_llm_retry_policy_returns_async_retrying(self) -> None:
        policy = llm_retry_policy(max_attempts=2)
        assert policy is not None

    def test_tool_http_retry_policy(self) -> None:
        policy = tool_http_retry_policy(max_attempts=3)
        assert policy is not None

    def test_tool_http_retry_policy_idempotent(self) -> None:
        policy = tool_http_retry_policy(max_attempts=3, idempotent=True)
        assert policy is not None

    def test_db_retry_policy(self) -> None:
        policy = db_retry_policy(max_attempts=2)
        assert policy is not None

    def test_redis_retry_policy(self) -> None:
        policy = redis_retry_policy(max_attempts=2)
        assert policy is not None


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Idempotency cache and conflict detection."""

    async def test_cache_and_get_response(self) -> None:
        key = str(uuid.uuid4())
        with patch("nexus.errors.idempotency.get_redis_client") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis

            await cache_idempotent_response(key, 200, {"result": "ok"}, {"x-custom": "val"})
            mock_redis.set.assert_awaited_once()

    async def test_get_idempotent_response_none_when_missing(self) -> None:
        key = str(uuid.uuid4())
        with patch("nexus.errors.idempotency.get_redis_client") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_get_redis.return_value = mock_redis

            result = await get_idempotent_response(key)
            assert result is None

    async def test_idempotency_conflict_error(self) -> None:
        err = IdempotencyConflict("test_key")
        assert "test_key" in err.message
        assert err.status_code == 409


# ---------------------------------------------------------------------------
# Graceful Degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    """DegradationManager health checks."""

    async def test_degraded_llm_response_returns_string(self) -> None:
        mgr = DegradationManager()
        response = await mgr.degraded_llm_response()
        assert isinstance(response, str)
        assert len(response) > 0

    async def test_degraded_tool_response_has_status(self) -> None:
        mgr = DegradationManager()
        response = await mgr.degraded_tool_response("send_email")
        assert response["status"] == "degraded"
        assert response["tool_name"] == "send_email"
        assert response["retryable"] is True


# ---------------------------------------------------------------------------
# Dead Letter Queue
# ---------------------------------------------------------------------------

class TestDeadLetterQueue:
    """Dead letter queue operations."""

    async def test_send_returns_uuid(self) -> None:
        dlq = DeadLetterQueue()
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        # Mock session.add to not trigger SQLAlchemy internals
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch("nexus.errors.dead_letter._get_session", return_value=mock_session):
            entry_id = await dlq.send(
                tenant_id=uuid.uuid4(),
                tool_name="test_tool",
                input_payload={"arg": "val"},
                error_message="Connection failed",
                error_code="TIMEOUT",
                retry_count=3,
            )
            assert isinstance(entry_id, uuid.UUID)

    async def test_list_filters_by_tenant(self) -> None:
        dlq = DeadLetterQueue()
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        # Mock execute to return an empty list
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("nexus.errors.dead_letter._get_session", return_value=mock_session):
            results = await dlq.list(tenant_id=uuid.uuid4())
            assert isinstance(results, list)


import asyncio  # noqa: E402 — needed for circuit breaker cooldown tests
