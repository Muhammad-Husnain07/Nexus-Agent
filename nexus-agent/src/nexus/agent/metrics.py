"""Post-execution metrics extraction from LangGraph checkpoint history.

Iterates checkpoint history to compute per-node timing, token usage, and
DAG structure without adding latency to the live streaming response.

No hardcoded node names — derives metrics dynamically from checkpoint metadata.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger("nexus.agent.metrics")


async def extract_turn_metrics(
    graph: Any,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Extract granular metrics for the last graph turn from checkpoint history.

    Iterates through checkpoints and computes:
    - Per-node latency (delta between consecutive checkpoints)
    - Total tokens consumed
    - Planner DAG size (number of tasks)
    - Executor retries
    - Router decision path

    Args:
        graph: Compiled LangGraph StateGraph.
        config: Runnable config with ``thread_id``.

    Returns:
        Dict with keys: total_latency_ms, per_node, total_tokens, dag_size,
        retry_count, router_decision, extraction_intent.
    """
    metrics: dict[str, Any] = {
        "total_latency_ms": 0,
        "per_node": {},
        "total_tokens": 0,
        "dag_size": 0,
        "retry_count": 0,
        "router_decision": "",
        "extraction_intent": "",
        "planner_tool_count": 0,
        "executor_failed_count": 0,
    }

    prev_ts = None
    prev_node = "__start__"

    try:
        async for cp in graph.aget_state_history(config):
            checkpoint = getattr(cp, "checkpoint", {})
            ts = checkpoint.get("ts") if isinstance(checkpoint, dict) else None
            metadata = getattr(cp, "metadata", {}) or {}
            step = metadata.get("step", 0) if isinstance(metadata, dict) else 0
            source = metadata.get("source", "") if isinstance(metadata, dict) else ""

            # Skip terminal states and input steps
            if source == "input" or step == 0:
                continue

            # Compute node latency from checkpoint timestamp delta
            if prev_ts and ts:
                from datetime import datetime
                try:
                    curr = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    prev = datetime.fromisoformat(prev_ts.replace("Z", "+00:00"))
                    delta_ms = int((curr - prev).total_seconds() * 1000)
                    metrics["per_node"][f"step_{step}"] = {
                        "source": source,
                        "latency_ms": delta_ms,
                    }
                    if prev_node != "__start__":
                        metrics["per_node"].setdefault(prev_node, {"latency_ms": 0})
                        metrics["per_node"][prev_node]["latency_ms"] = (
                            metrics["per_node"][prev_node].get("latency_ms", 0) + delta_ms
                        )
                    metrics["total_latency_ms"] += delta_ms
                except Exception:
                    pass

            prev_ts = ts
            prev_node = source

            # Try to get state values for metrics
            try:
                snapshot = await graph.aget_state(cp.config if hasattr(cp, "config") else config)
                if snapshot and hasattr(snapshot, "values"):
                    vals = snapshot.values or {}

                    # Router decision
                    if not metrics["router_decision"]:
                        qtype = vals.get("_query_type", "")
                        if qtype:
                            metrics["router_decision"] = qtype

                    # Extraction intent
                    if not metrics["extraction_intent"]:
                        ext = vals.get("_extraction_result", {})
                        if ext and isinstance(ext, dict):
                            intent = ext.get("intent", "")
                            if intent:
                                metrics["extraction_intent"] = str(intent)

                    # Planner DAG size
                    plan = vals.get("_execution_plan", {})
                    if plan and isinstance(plan, dict):
                        waves = plan.get("waves", [])
                        task_count = sum(len(w.get("tasks", [])) for w in waves)
                        if task_count > metrics["dag_size"]:
                            metrics["dag_size"] = task_count
                            metrics["planner_tool_count"] = len(plan.get("tool_names", []))

                    # Executor retries
                    retry_counts = vals.get("_tool_retry_counts", {})
                    if retry_counts:
                        metrics["retry_count"] = max(
                            metrics["retry_count"],
                            max(retry_counts.values()) if retry_counts else 0,
                        )

                    # Failed tasks
                    failed = vals.get("_executor_failed", [])
                    if failed:
                        metrics["executor_failed_count"] = len(failed)

                    # Tokens
                    tokens = vals.get("_total_tokens", 0)
                    if tokens:
                        metrics["total_tokens"] = max(metrics["total_tokens"], tokens)

            except Exception:
                continue

    except Exception:
        logger.warning("metrics.extraction_failed")

    return metrics
