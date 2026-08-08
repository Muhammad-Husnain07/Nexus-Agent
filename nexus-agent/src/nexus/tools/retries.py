"""Per-tool HTTP retry policy — 5xx, 408, 429 with exponential backoff.

Also provides category-aware delay calculation for use with
``SemanticRetryHandler`` when error classification is available.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from nexus.config.settings import get_settings

logger = logging.getLogger("nexus.tools.retries")


def _get_retry_settings() -> Any:
    """Return tools retry settings, or fallback defaults."""
    try:
        s = get_settings()
        return {
            "retryable_codes": tuple(s.tools.retryable_status_codes),
            "max_attempts": s.tools.max_retries + 1,
            "backoff_base": s.tools.retry_backoff_s,
            "backoff_max": max(s.tools.retry_backoff_s * 8, 30.0),
        }
    except Exception:
        return {
            "retryable_codes": (408, 429, 500, 502, 503, 504),
            "max_attempts": 3,
            "backoff_base": 1.0,
            "backoff_max": 30.0,
        }


class _HttpRetryPredicate:
    """Retry predicate that matches HTTP status codes and transport errors."""

    def __init__(self) -> None:
        self._retryable_codes: tuple[int, ...] = _get_retry_settings()["retryable_codes"]

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
    return status in _get_retry_settings()["retryable_codes"]


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


def category_retry_delay(category: str, attempt: int, retry_after_hint: float | None = None) -> float:
    """Return an appropriate delay for the given error category.

    Args:
        category: Error category string (e.g. 'transient_network', 'rate_limit').
        attempt: Zero-based retry attempt number.
        retry_after_hint: Explicit delay hint from Retry-After header.

    Returns:
        Delay in seconds.
    """
    import random  # noqa: PLC0415
    rs = _get_retry_settings()

    if retry_after_hint is not None and category == "transient_rate_limit":
        return retry_after_hint

    if category == "transient_rate_limit":
        return min(rs["backoff_base"] * (2 ** attempt), rs["backoff_max"]) + random.uniform(0, 1)

    if category in ("transient_network", "transient_service"):
        return min(rs["backoff_base"] * (2 ** attempt), rs["backoff_max"]) + random.uniform(0, 1)

    if category in ("permanent_schema", "permanent_argument"):
        return 0.0  # retry immediately after param fix

    return rs["backoff_base"]  # default fallback


def http_retry_policy(
    max_attempts: int | None = None,
    backoff_base_s: float | None = None,
    backoff_max_s: float | None = None,
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
    rs = _get_retry_settings()
    return AsyncRetrying(
        stop=stop_after_attempt(max_attempts if max_attempts is not None else rs["max_attempts"]),
        wait=wait_exponential(multiplier=1,
                              min=backoff_base_s if backoff_base_s is not None else rs["backoff_base"],
                              max=backoff_max_s if backoff_max_s is not None else rs["backoff_max"])
        + wait_random(0, 1),
        retry=retry_if_exception(_HttpRetryPredicate()),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
