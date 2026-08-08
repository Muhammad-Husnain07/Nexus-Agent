"""ArtifactGraph — in-memory typed artifact store.

Maps ``artifact_id -> ArtifactBase``.  Provides lookup by type and by
execution ID.  Used by the ResponseNode and AggregatorNode to access
structured tool outputs without raw JSON blobs in the graph state.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from nexus.artifacts.base import ArtifactBase


class ArtifactGraph:
    """In-memory typed artifact map.

    Thread-safe for concurrent reads within a single agent run.
    Not serialized — artifacts live only during the active execution.
    """

    def __init__(self) -> None:
        self._artifacts: dict[UUID, ArtifactBase] = {}
        self._by_type: dict[str, list[UUID]] = {}
        self._by_execution: dict[str, list[UUID]] = {}

    def register(self, artifact: ArtifactBase) -> None:
        """Register an artifact in the graph."""
        self._artifacts[artifact.artifact_id] = artifact
        self._by_type.setdefault(artifact.type, []).append(artifact.artifact_id)
        if artifact.execution_id:
            self._by_execution.setdefault(artifact.execution_id, []).append(artifact.artifact_id)

    def get(self, artifact_id: UUID) -> ArtifactBase | None:
        """Retrieve an artifact by its UUID."""
        return self._artifacts.get(artifact_id)

    def get_by_type(self, type_str: str) -> list[ArtifactBase]:
        """Retrieve all artifacts of a given type."""
        ids = self._by_type.get(type_str, [])
        return [self._artifacts[a_id] for a_id in ids if a_id in self._artifacts]

    def get_by_execution(self, execution_id: str) -> list[ArtifactBase]:
        """Retrieve all artifacts produced by a given execution event."""
        ids = self._by_execution.get(execution_id, [])
        return [self._artifacts[a_id] for a_id in ids if a_id in self._artifacts]

    def all(self) -> list[ArtifactBase]:
        """Return all registered artifacts."""
        return list(self._artifacts.values())

    def clear(self) -> None:
        """Clear all artifacts (called between turns)."""
        self._artifacts.clear()
        self._by_type.clear()
        self._by_execution.clear()

    def __len__(self) -> int:
        return len(self._artifacts)

    def __contains__(self, artifact_id: UUID) -> bool:
        return artifact_id in self._artifacts


# Per-session artifact graphs — keyed by session id. A module-level SINGLE
# graph would leak tool data across concurrent sessions (user A's results
# rendered into user B's response) and race with `reset` mid-run.
_GRAPHS: dict[str, ArtifactGraph] = {}


def get_artifact_graph(session_id: str = "") -> ArtifactGraph:
    """Return the ArtifactGraph for the given session.

    Session-scoped: every session gets an isolated graph, so concurrent
    runs never observe each other's tool outputs.

    Args:
        session_id: The conversation session id. When empty, a shared
            fallback graph is returned (callers without a session).

    Returns:
        The session's ArtifactGraph (created on first access).
    """
    key = session_id or "_default"
    if key not in _GRAPHS:
        _GRAPHS[key] = ArtifactGraph()
    return _GRAPHS[key]


def reset_artifact_graph(session_id: str = "") -> None:
    """Clear and drop the artifact graph for a session (between turns).

    Args:
        session_id: The conversation session id. When empty, the shared
            fallback graph is reset.
    """
    key = session_id or "_default"
    graph = _GRAPHS.pop(key, None)
    if graph is not None:
        graph.clear()


def reset_all_artifact_graphs() -> None:
    """Drop every session's artifact graph (process shutdown / tests)."""
    for graph in _GRAPHS.values():
        graph.clear()
    _GRAPHS.clear()
