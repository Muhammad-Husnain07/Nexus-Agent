"""Checkpoint manager — named checkpoint lookup via LangGraph state history.

No hardcoded checkpoint names. Queries LangGraph's ``aget_state_history()``
to find checkpoints by the ``next`` node field. Every node in the graph
automatically gets recovery support.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger("nexus.agent.checkpoint_manager")


async def find_checkpoint_before(
    graph: Any,
    config: dict[str, Any],
    target_node: str,
) -> Any | None:
    """Find the checkpoint right before ``target_node`` was about to execute.

    Iterates through LangGraph's state history and checks each checkpoint's
    ``next`` field (via ``aget_state``) to find the one where ``target_node``
    was the next node to execute.

    Args:
        graph: Compiled LangGraph StateGraph.
        config: Runnable config with ``thread_id``.
        target_node: Node name to find (e.g. ``"PlannerNode"``, ``"ExecutorNode"``).

    Returns:
        The ``StateSnapshot`` at that checkpoint, or None.
    """
    history = []
    async for cp in graph.aget_state_history(config):
        history.append(cp)
        if len(history) >= 100:
            break

    for cp_record in history:
        if not hasattr(cp_record, "config"):
            continue
        cp_config = cp_record.config
        snapshot = await graph.aget_state(cp_config)
        if snapshot is None:
            continue
        next_nodes = snapshot.next if hasattr(snapshot, "next") else []
        if isinstance(next_nodes, (list, tuple)) and target_node in next_nodes:
            return snapshot
        if next_nodes == target_node:
            return snapshot

    return None


async def find_latest_checkpoint(
    graph: Any,
    config: dict[str, Any],
) -> Any | None:
    """Get the penultimate checkpoint, skipping the terminal state."""
    history = []
    async for cp in graph.aget_state_history(config):
        history.append(cp)
        if len(history) >= 100:
            break

    if not history:
        return None

    # Skip the first (most recent/terminal) — get the second one
    target_idx = 1 if len(history) > 1 else 0
    cp_record = history[target_idx]
    cp_config = cp_record.config
    snapshot = await graph.aget_state(cp_config)
    return snapshot
