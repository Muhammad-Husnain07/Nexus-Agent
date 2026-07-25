"""Compiled Capability Graph Reader — loaded at runtime, never computes ontology.

The runtime reads a ``CompiledCapabilityGraph`` produced by ``registry_compiler.py``.
All ontology lookups, schema validation, and adjacency computation happen at compile
time. The runtime simply traverses pre-computed structures.

No hardcoded capability names. All data comes from the compiled graph JSON.
"""

from __future__ import annotations

import json
import os
from typing import Any

import structlog

from nexus.compiler.registry_compiler import CompiledCapabilityGraph

logger = structlog.get_logger("nexus.compiler.compiled_graph")

# Module-level cache
_compiled_graph: CompiledCapabilityGraph | None = None
_COMPILED_GRAPH_PATH: str = "compiled_registry.json"


def load_compiled_graph(path: str | None = None) -> CompiledCapabilityGraph | None:
    """Load the compiled capability graph from a JSON file.

    Args:
        path: Path to compiled graph JSON. If None, uses default path.

    Returns:
        ``CompiledCapabilityGraph`` or None if not found.
    """
    global _compiled_graph

    filepath = path or _COMPILED_GRAPH_PATH
    if not os.path.exists(filepath):
        logger.warning("compiled_graph.not_found", path=filepath)
        return None

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
        return None


def get_compiled_graph() -> CompiledCapabilityGraph | None:
    """Get the cached compiled capability graph.

    Returns the module-level cached graph if already loaded, otherwise None.
    Call ``load_compiled_graph()`` first to populate the cache.
    """
    return _compiled_graph


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
    g = graph or _compiled_graph
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
    g = graph or _compiled_graph
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
    g = graph or _compiled_graph
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
