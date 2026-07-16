"""Centralized tenacity retry policies for LLM calls, tool HTTP, DB ops, and Redis ops."""

from __future__ import annotations

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
