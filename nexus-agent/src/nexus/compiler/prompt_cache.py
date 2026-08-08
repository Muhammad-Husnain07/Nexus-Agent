"""Memory-aware multi-process cache for compiled prompts.

Uses a local LRU-like cache with memory budgeting (not item counting).
Optionally delegates to a shared cache for multi-process coherence.
"""

from __future__ import annotations

import json
import sys
from abc import ABC, abstractmethod
from typing import Any


def _estimate_size(obj: Any) -> int:
    """Recursively estimate memory usage of an object."""
    if isinstance(obj, dict):
        return sys.getsizeof(obj) + sum(_estimate_size(k) + _estimate_size(v) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return sys.getsizeof(obj) + sum(_estimate_size(i) for i in obj)
    if isinstance(obj, str):
        return sys.getsizeof(obj)
    return sys.getsizeof(obj)


class MemoryAwareCache:
    """Local cache that evicts by memory usage, not item count.

    Attributes:
        max_memory_bytes: Maximum memory usage before eviction.
    """

    def __init__(self, max_memory_mb: int = 100) -> None:
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self._cache: dict[str, Any] = {}
        self._memory_usage: int = 0

    def get(self, key: str) -> Any:
        return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        value_size = _estimate_size(value)
        # Evict until there's room
        while self._memory_usage + value_size > self.max_memory_bytes and self._cache:
            evicted_key = next(iter(self._cache))
            evicted_val = self._cache.pop(evicted_key)
            self._memory_usage -= _estimate_size(evicted_val)
        self._cache[key] = value
        self._memory_usage += value_size


class AbstractSharedCache(ABC):
    """Abstract interface for a shared (e.g. Redis) cache."""

    @abstractmethod
    def get(self, key: str) -> Any:
        ...

    @abstractmethod
    def set(self, key: str, value: str, ttl: int) -> None:
        ...


class PromptCache:
    """Two-tier prompt cache with local memory + optional shared backend.

    Attributes:
        local_cache: Memory-aware local cache.
        shared_cache: Optional shared cache (e.g. Redis).
    """

    def __init__(self, local_memory_mb: int = 50, shared_cache: AbstractSharedCache | None = None) -> None:
        self.local_cache = MemoryAwareCache(max_memory_mb=local_memory_mb)
        self.shared_cache = shared_cache

    def get(self, fp: str, model: str, budget: int) -> Any:
        """Look up a cached prompt by fingerprint."""
        key = f"{fp}:{model}:{budget}"
        cached = self.local_cache.get(key)
        if cached is not None:
            return cached
        if self.shared_cache is not None:
            raw = self.shared_cache.get(key)
            if raw is not None:
                try:
                    return json.loads(raw).get("prompt", raw)
                except (json.JSONDecodeError, TypeError):
                    return raw
        return None

    def set(self, fp: str, model: str, budget: int, value: list[dict]) -> None:
        """Store a rendered prompt in the cache."""
        key = f"{fp}:{model}:{budget}"
        self.local_cache.set(key, value)
        if self.shared_cache is not None:
            self.shared_cache.set(key, json.dumps({"prompt": value}), ttl=300)
