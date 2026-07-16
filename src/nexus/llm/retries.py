"""Tenacity retry policy for LLM calls.

Defines which LiteLLM exceptions are retryable and configures exponential
backoff with jitter.
"""

from __future__ import annotations

import logging

from litellm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    InternalServerError,
    RateLimitError,
)
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)
from tenacity.stop import stop_never

logger = logging.getLogger("nexus.llm.retries")

RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    RateLimitError,
    APIConnectionError,
    InternalServerError,
)
NON_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
)


def llm_retry_policy(
    max_attempts: int = 5,
    min_wait_s: float = 1.0,
    max_wait_s: float = 32.0,
) -> AsyncRetrying:
    """Create a tenacity retry policy for LLM calls.

    Retries on rate limits, connection errors, server errors, and timeouts.
    Does NOT retry on authentication errors, bad requests, or content policy
    violations.

    Args:
        max_attempts: Maximum number of attempts before giving up.
        min_wait_s: Minimum exponential backoff in seconds.
        max_wait_s: Maximum exponential backoff in seconds.

    Returns:
        A configured ``AsyncRetrying`` instance.
    """
    return AsyncRetrying(
        stop=(stop_never if max_attempts < 1 else stop_after_attempt(max_attempts)),
        wait=wait_exponential(multiplier=1, min=min_wait_s, max=max_wait_s) + wait_random(0, 1),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


def is_retryable(exc: BaseException) -> bool:
    """Return True if the exception is a retryable LLM error."""
    return isinstance(exc, RETRYABLE_EXCEPTIONS)


def is_non_retryable(exc: BaseException) -> bool:
    """Return True if the exception is a known non-retryable LLM error."""
    return isinstance(exc, NON_RETRYABLE_EXCEPTIONS)
