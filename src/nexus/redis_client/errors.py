"""Redis client errors."""

from __future__ import annotations


class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, key: str, retry_after_s: float) -> None:
        self.key = key
        self.retry_after_s = retry_after_s
        super().__init__(f"Rate limit exceeded for key {key}: retry after {retry_after_s}s")


class LockAcquisitionError(Exception):
    """Raised when a distributed lock cannot be acquired."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Failed to acquire lock: {name}")
