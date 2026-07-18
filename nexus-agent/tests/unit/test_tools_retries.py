"""Unit tests for tool HTTP retry policy."""

from __future__ import annotations

import httpx

from nexus.tools.retries import is_retryable_status, parse_retry_after


class TestIsRetryableStatus:
    def test_408_is_retryable(self) -> None:
        assert is_retryable_status(408) is True

    def test_429_is_retryable(self) -> None:
        assert is_retryable_status(429) is True

    def test_503_is_retryable(self) -> None:
        assert is_retryable_status(503) is True

    def test_400_not_retryable(self) -> None:
        assert is_retryable_status(400) is False

    def test_200_not_retryable(self) -> None:
        assert is_retryable_status(200) is False


class TestParseRetryAfter:
    def test_seconds_format(self) -> None:
        resp = httpx.Response(429, headers={"Retry-After": "5"})
        result = parse_retry_after(resp)
        assert result == 5.0

    def test_missing_header(self) -> None:
        resp = httpx.Response(429)
        result = parse_retry_after(resp)
        assert result is None

    def test_invalid_header(self) -> None:
        resp = httpx.Response(429, headers={"Retry-After": "not-a-number"})
        result = parse_retry_after(resp)
        # Should not crash; returns None if parsing fails
        assert result is None or result >= 0
