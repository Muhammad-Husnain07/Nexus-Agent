"""Input Enrichment Pass — injects API-specific parameters from registry metadata.

Reads each ``ToolNode``'s ``capability``, looks up the capability's
``intent_profiles`` and ``input_policy`` from the DB registry, and
enriches the node's ``inputs`` with:

1. **Intent Profiles** — If the LLM specified a ``"profile"`` key in inputs
   (e.g. ``{"profile": "current"}``), the matching profile's params are
   merged in and the ``"profile"`` key is removed.

2. **Input Policy Defaults** — Any defaults defined in
   ``input_policy.defaults`` are merged in (LLM inputs take precedence).

3. **Computed Fields** — Keys listed in ``input_policy.computed`` are
   resolved from a user preferences context (passed to the pass).

Pure-ish: no I/O beyond the registry lookup (which is cached).
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.compiler.ir_models import ExecutionGraph, PhysicalNode, ToolNode
from nexus.registry.client import RegistryClient

logger = structlog.get_logger("nexus.compiler.passes.input_enrichment")

# Runs FIRST — enriches inputs before any structural pass examines them.
PRIORITY = 10


async def run(
    graph: ExecutionGraph,
    registry: RegistryClient,
    user_preferences: dict[str, Any] | None = None,
) -> ExecutionGraph:
    """Enrich ToolNode inputs from registry metadata.

    Args:
        graph: The current ``ExecutionGraph``.
        registry: ``RegistryClient`` for DB-backed capability metadata.
        user_preferences: Optional dict for resolving ``computed`` field paths.

    Returns:
        ``ExecutionGraph`` with enriched ``ToolNode.inputs``.
    """
    user_prefs = user_preferences or {}
    enriched_nodes: dict[str, PhysicalNode] = {}

    for nid, node in graph.nodes.items():
        if isinstance(node, ToolNode):
            new_node = await _enrich_tool_node(node, registry, user_prefs)
            enriched_nodes[nid] = new_node
        else:
            enriched_nodes[nid] = node

    if enriched_nodes == graph.nodes:
        return graph

    data = graph.model_dump()
    data.pop("nodes", None)
    return ExecutionGraph(**data, nodes=enriched_nodes)


async def _enrich_tool_node(
    node: ToolNode,
    registry: RegistryClient,
    user_prefs: dict[str, Any],
) -> ToolNode:
    """Enrich a single ToolNode's inputs."""
    capability_name = node.capability
    new_inputs = dict(node.inputs)

    # 1. Resolve intent profile and merge its params
    profile_name = new_inputs.pop("profile", None)
    if profile_name:
        profiles = await registry.get_intent_profiles(capability_name)
        profile_params = profiles.get(profile_name, {})
        if profile_params:
            new_inputs.update(profile_params)
            logger.debug("input_enrichment.profile_applied", cap=capability_name, profile=profile_name)

    # 2. Apply input policy defaults (LLM inputs take precedence)
    policy = await registry.get_input_policy(capability_name)
    defaults = policy.get("defaults", {})
    for key, val in defaults.items():
        if key not in new_inputs:
            new_inputs[key] = val

    # 3. Resolve computed fields from user preferences
    computed = policy.get("computed", {})
    for key, path in computed.items():
        if key not in new_inputs:
            resolved = _deep_resolve(path, user_prefs)
            if resolved is not None:
                new_inputs[key] = resolved

    # 4. Unwrap "item" wrapper: if inputs contain a single "item" key,
    #    the LLM produced a MapNode-style payload.  Flatten the title
    #    so any tool receives the correct top-level field.
    if "item" in new_inputs and isinstance(new_inputs["item"], dict) and len(new_inputs) <= 2:
        item_data = new_inputs.pop("item")
        item_title = item_data.get("title", "")
        if item_title and "title" not in new_inputs:
            new_inputs["title"] = item_title

    # 5. Apply field_mapping: rename input keys to match API expectations
    #    e.g., {"query": "q"} means rename the "query" key to "q"
    field_mapping = policy.get("field_mapping", {})
    if field_mapping:
        for old_key, new_key in field_mapping.items():
            if old_key in new_inputs:
                new_inputs[new_key] = new_inputs.pop(old_key)

    if new_inputs == node.inputs:
        return node

    return node.model_copy(update={"inputs": new_inputs})


def _deep_resolve(path: str, data: dict[str, Any]) -> Any:
    """Resolve a dot-separated path in a nested dict (e.g. ``"user.units"``)."""
    if not path or not data:
        return None
    parts = path.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current
