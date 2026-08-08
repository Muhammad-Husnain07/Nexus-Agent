"""Tasks package — persistent task registry, queue, worker, and scheduler."""

from nexus.tasks.registry import TaskRegistry
from nexus.tasks.scheduler import Scheduler
from nexus.tasks.worker import Worker, register_executor

# Import executors so default task types are registered
from nexus.tasks import executors as _executors  # noqa: F401

__all__ = ["TaskRegistry", "Scheduler", "Worker", "register_executor"]
