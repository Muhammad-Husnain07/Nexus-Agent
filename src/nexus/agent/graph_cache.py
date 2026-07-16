"""Shared in-memory cache of compiled LangGraph instances.

Both ``api.py`` and ``approvals.py`` need access to the compiled
``StateGraph`` for a given session so they can resume from interrupts.
This module provides a single source of truth so the cache is not
duplicated.
"""

from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

_graphs: dict[str, CompiledStateGraph] = {}


def get_graph(session_id: str) -> CompiledStateGraph | None:
    """Return the compiled graph for *session_id*, or ``None``."""
    return _graphs.get(session_id)


def set_graph(session_id: str, graph: CompiledStateGraph) -> None:
    """Cache a compiled graph under *session_id*."""
    _graphs[session_id] = graph


def remove_graph(session_id: str) -> None:
    """Remove the cached graph for *session_id*."""
    _graphs.pop(session_id, None)


def has_graph(session_id: str) -> bool:
    """Return ``True`` if a graph is cached for *session_id*."""
    return session_id in _graphs


def graph_count() -> int:
    """Return the number of currently cached graphs."""
    return len(_graphs)


def clear_all() -> None:
    """Remove all cached graphs (used in tests)."""
    _graphs.clear()
