"""Queue provider interface — pluggable task queue transport.

The orchestrator depends on this ABC, never on a concrete transport.
Built-in adapter: Redis Streams with consumer groups (performance,
reliability, retries, horizontal scaling). External MQs (RabbitMQ/SQS/
Kafka) can be added as adapters without changing business logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

STREAM = "nexus:tasks"


class TaskQueue(ABC):
    """Abstract task queue used by the worker + orchestrator."""

    @abstractmethod
    async def enqueue(self, task_id: str, payload: dict[str, Any], group: str = "default") -> None:
        """Publish a task to the queue."""

    @abstractmethod
    async def claim(self, group: str = "default", consumer: str = "worker") -> dict[str, Any] | None:
        """Claim one task (blocking briefly); returns {task_id, payload} or None."""

    @abstractmethod
    async def ack(self, task_id: str, group: str = "default") -> None:
        """Acknowledge a completed task."""

    @abstractmethod
    async def nack(self, task_id: str, group: str = "default") -> None:
        """Negative-acknowledge a failed task (requeue for retry)."""
