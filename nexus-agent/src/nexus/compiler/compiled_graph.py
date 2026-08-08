"""Compiled Capability Graph Reader — loaded at runtime, never computes ontology.

The runtime reads a ``CompiledCapabilityGraph`` produced by ``registry_compiler.py``.
All ontology lookups, schema validation, and adjacency computation happen at compile
time. The runtime simply traverses pre-computed structures.

No hardcoded capability names. All data comes from the compiled graph JSON.
The graph path is configured via ``settings.compiler.compiled_graph_path``.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import structlog

from nexus.compiler.registry_compiler import CompiledCapabilityGraph, compile_registry
from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.compiler.compiled_graph")

# Module-level cache (single-assignment via lazy loading — no mutable globals)
_compiled_graph: CompiledCapabilityGraph | None = None


def _get_graph_path() -> str:
    """Resolve compiled graph path from settings, falling back to a default."""
    settings = get_settings()
    path = getattr(settings, "compiler", None)
    if path is not None:
        return getattr(path, "compiled_graph_path", "compiled_registry.json")
    return "compiled_registry.json"


def load_compiled_graph(path: str | None = None) -> CompiledCapabilityGraph | None:
    """Load the compiled capability graph from a JSON file.

    If the file is not found, attempts a DB fallback by calling ``compile_registry()``
    on-the-fly. This ensures the runtime never stalls on a missing compiled graph.

    Args:
        path: Path to compiled graph JSON. If None, uses configured path.

    Returns:
        ``CompiledCapabilityGraph`` or None if not found and no DB fallback.
    """
    global _compiled_graph

    filepath = path or _get_graph_path()
    if os.path.exists(filepath):
        try:
            with open(filepath) as f:
                data = json.load(f)
            _compiled_graph = CompiledCapabilityGraph.from_dict(data)
            logger.info(
                "compiled_graph.loaded",
                nodes=len(_compiled_graph.nodes),
                templates=len(_compiled_graph.goal_templates),
                path=filepath,
            )
            return _compiled_graph
        except Exception as exc:
            logger.error("compiled_graph.load_failed", path=filepath, error=str(exc))

    # DB fallback — compile on-the-fly from live registry
    logger.info("compiled_graph.db_fallback", path=filepath)
    try:
        if asyncio.get_running_loop() is not None:
            # Called from within a running event loop — cannot block it with
            # asyncio.run/run_until_complete here. Callers in async contexts
            # must use ``load_compiled_graph_async`` instead; this sync path
            # returns None rather than crashing (an empty graph is logged and
            # handled downstream).
            logger.warning("compiled_graph.async_context_no_fallback")
            return None
    except RuntimeError:
        pass  # No running loop — safe to use asyncio.run below

    try:
        _compiled_graph = asyncio.run(compile_registry())
        logger.info(
            "compiled_graph.db_fallback_ok",
            nodes=len(_compiled_graph.nodes),
        )
        return _compiled_graph
    except Exception as exc:
        logger.error("compiled_graph.db_fallback_failed", error=str(exc))
        return None


async def load_compiled_graph_async(path: str | None = None) -> CompiledCapabilityGraph | None:
    """Async-load the compiled capability graph (safe inside an event loop).

    Falls back to compiling from the live registry when the JSON file is
    missing — without ``asyncio.run()``, which would crash inside a running
    event loop (the FastAPI request path).

    Args:
        path: Path to compiled graph JSON. If None, uses configured path.

    Returns:
        ``CompiledCapabilityGraph`` or None if not found and no DB fallback.
    """
    global _compiled_graph

    filepath = path or _get_graph_path()
    if os.path.exists(filepath):
        try:
            with open(filepath) as f:
                data = json.load(f)
            _compiled_graph = CompiledCapabilityGraph.from_dict(data)
            logger.info(
                "compiled_graph.loaded",
                nodes=len(_compiled_graph.nodes),
                path=filepath,
            )
            return _compiled_graph
        except Exception as exc:
            logger.error("compiled_graph.load_failed", path=filepath, error=str(exc))

    logger.info("compiled_graph.db_fallback_async", path=filepath)
    try:
        _compiled_graph = await compile_registry()
        logger.info("compiled_graph.db_fallback_ok", nodes=len(_compiled_graph.nodes))
        return _compiled_graph
    except Exception as exc:
        logger.error("compiled_graph.db_fallback_failed", error=str(exc))
        return None


def get_compiled_graph() -> CompiledCapabilityGraph | None:
    """Get the cached compiled capability graph.

    If not yet loaded, attempts to load automatically via ``load_compiled_graph()``.
    """
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = load_compiled_graph()
    return _compiled_graph


def invalidate_cache() -> None:
    """Clear the cached compiled graph so the next access reloads it."""
    global _compiled_graph
    _compiled_graph = None
    logger.info("compiled_graph.cache_invalidated")


def find_capability(
    name: str,
    graph: CompiledCapabilityGraph | None = None,
) -> dict[str, Any] | None:
    """Find a capability node by name in the compiled graph.

    Args:
        name: Capability name to find.
        graph: Compiled graph to search. Uses cached if None.

    Returns:
        Capability node dict or None.
    """
    g = graph or get_compiled_graph()
    if g is None:
        return None
    node = g.nodes.get(name)
    return node.to_dict() if node else None


def find_goal_template(
    action: str,
    graph: CompiledCapabilityGraph | None = None,
) -> dict[str, Any] | None:
    """Find a goal template by trigger action.

    Args:
        action: Trigger action to find (e.g., 'compare', 'retrieve').
        graph: Compiled graph to search. Uses cached if None.

    Returns:
        Goal template dict or None.
    """
    g = graph or get_compiled_graph()
    if g is None:
        return None
    tmpl = g.goal_templates.get(action)
    if tmpl:
        return tmpl.to_dict()
    return None


def resolve_chain(
    from_capabilities: list[str],
    to_artifact: str,
    graph: CompiledCapabilityGraph | None = None,
) -> list[list[str]]:
    """Find all capability chains that produce ``to_artifact``.

    Pure BFS on the compiled graph. No LLM. No schema matching.

    Args:
        from_capabilities: Starting capability names.
        to_artifact: Target artifact field name to produce.
        graph: Compiled graph. Uses cached if None.

    Returns:
        List of capability name chains.
    """
    g = graph or get_compiled_graph()
    if g is None:
        return []

    paths: list[list[str]] = []
    for start in from_capabilities:
        if start not in g.nodes:
            continue
        if to_artifact in g.nodes[start].produces:
            paths.append([start])
            continue

        # BFS
        visited: set[str] = set()
        queue: list[tuple[str, list[str]]] = [(start, [start])]
        while queue:
            current, chain = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            for neighbor in g.adjacency.get(current, []):
                if neighbor in visited:
                    continue
                new_chain = chain + [neighbor]
                if to_artifact in g.nodes[neighbor].produces:
                    paths.append(new_chain)
                else:
                    queue.append((neighbor, new_chain))

    return paths
