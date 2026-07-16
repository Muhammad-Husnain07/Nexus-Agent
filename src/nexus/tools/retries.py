"""Per-tool HTTP retry policy — 5xx, 408, 429 with exponential backoff."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

logger = logging.getLogger("nexus.tools.retries")

RETRYABLE_STATUS_CODES: tuple[int, ...] = (408, 429, 500, 502, 503, 504)

MAX_ATTEMPTS_DEFAULT: int = 3
BACKOFF_BASE_S: float = 1.0
BACKOFF_MAX_S: float = 30.0


class _HttpRetryPredicate:
    """Retry predicate that matches HTTP status codes and transport errors."""

    _retryable_codes: tuple[int, ...] = RETRYABLE_STATUS_CODES

    def __call__(self, exc: BaseException) -> bool:
        if isinstance(exc, httpx.TimeoutException):
            return True
        if isinstance(exc, httpx.TransportError):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in self._retryable_codes
        return False


def is_retryable_status(status: int) -> bool:
    """Return True if the HTTP status code warrants a retry."""
    return status in RETRYABLE_STATUS_CODES


def parse_retry_after(response: httpx.Response) -> float | None:
    """Extract a delay from the ``Retry-After`` header.

    Supports both seconds-as-integer and HTTP-date formats.
    Returns ``None`` if the header is missing or unparseable.
    """
    raw = response.headers.get("Retry-After")
    if not raw:
        return None

    # Try seconds-as-integer first
    try:
        return float(raw)
    except ValueError:
        pass

    # Try HTTP-date format
    try:
        dt = parsedate_to_datetime(raw)
        now = datetime.now(UTC)
        delay = (dt - now).total_seconds()
        return max(0.0, delay)
    except (ValueError, OSError):
        return None


def http_retry_policy(
    max_attempts: int = MAX_ATTEMPTS_DEFAULT,
    backoff_base_s: float = BACKOFF_BASE_S,
    backoff_max_s: float = BACKOFF_MAX_S,
) -> AsyncRetrying:
    """Create a tenacity retry policy for tool HTTP calls.

    Retries on retryable status codes (408, 429, 5xx), transport errors,
    and timeouts. Uses exponential backoff with jitter.

    Args:
        max_attempts: Maximum HTTP requests per tool call (including first).
        backoff_base_s: Initial backoff in seconds.
        backoff_max_s: Maximum backoff in seconds.

    Returns:
        A configured ``AsyncRetrying`` instance.
    """
    return AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=backoff_base_s, max=backoff_max_s)
        + wait_random(0, 1),
        retry=retry_if_exception(_HttpRetryPredicate()),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
