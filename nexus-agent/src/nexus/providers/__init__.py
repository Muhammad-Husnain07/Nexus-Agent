"""Provider layer — pluggable infrastructure adapters (auth, queue, vector).

The orchestrator depends on these interfaces, never on concrete transports:
swap deployments without changing orchestration logic.
"""

from nexus.providers.auth import AuthProvider, Identity, get_auth_provider
from nexus.providers.queue import TaskQueue, get_queue

__all__ = [
    "AuthProvider",
    "Identity",
    "TaskQueue",
    "get_auth_provider",
    "get_queue",
]
