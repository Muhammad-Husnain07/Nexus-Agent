"""risk_gate — HITL interrupt for high-risk tool tasks.

Reads ``dag_tasks`` and ``available_tools`` from state.  For each task
whose tool has ``risk_level = "high"`` or ``requires_approval = True``,
triggers a LangGraph ``interrupt()`` to pause execution for human approval.

This is a dedicated graph node — the existing approval checks inside
``tool_executor`` remain as a secondary safety net.
"""

from __future__ import annotations

from typing import Any

import structlog
from langgraph.types import interrupt

from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.tools.schemas import ToolRead

logger = structlog.get_logger("nexus.agent.nodes.risk_gate")


async def risk_gate(state: AgentState) -> dict[str, Any]:
    """Check each pending DAG task for approval requirements.

    For every task in ``dag_tasks`` that has a matching tool in
    ``available_tools``, checks whether the tool requires approval
    (``requires_approval=True`` or ``risk_level in ("medium","high")``).

    If any task requires approval, triggers an ``interrupt()`` and
    pauses the graph.  The interrupt payload includes tool name, inputs,
    and risk level for the frontend to display.

    Returns:
        Dict with ``_requires_approval`` (bool) and ``_approval_tasks``
        (list of task IDs that need approval).
    """
    tasks: list[dict[str, Any]] = state.get("dag_tasks", [])
    tools: list[dict[str, Any]] = state.get("available_tools", [])
    tool_map: dict[str, dict[str, Any]] = {t["name"]: t for t in tools}
    settings = get_settings().agent

    approval_tasks: list[dict[str, Any]] = []
    for task in tasks:
        if task.get("id") in (state.get("dag_results") or {}):
            continue
        tool_name = task.get("tool_name")
        if not tool_name:
            approaches = task.get("approaches", [])
            if approaches:
                tool_name = approaches[0].get("tool_name")
        if not tool_name or tool_name not in tool_map:
            continue

        meta = tool_map[tool_name]
        read = ToolRead(
            id=meta.get("id", ""),
            name=meta.get("name", ""),
            description=meta.get("description", ""),
            purpose=meta.get("purpose", ""),
            tool_type=meta.get("tool_type", "http_api"),
            endpoint_url=meta.get("endpoint_url", ""),
            mcp_server_url=meta.get("mcp_server_url", ""),
            http_method=meta.get("http_method", "GET"),
            auth_type=meta.get("auth_type", "none"),
            auth_ref=meta.get("auth_ref", ""),
            input_schema=meta.get("input_schema", {}),
            output_schema=meta.get("output_schema", {}),
            validation_rules=meta.get("validation_rules", {}),
            examples=meta.get("examples", []),
            tags=meta.get("tags", []),
            category=meta.get("category", "general"),
            requires_approval=meta.get("requires_approval", False),
            risk_level=meta.get("risk_level", "low"),
            enabled=meta.get("enabled", True),
            rate_limit_per_minute=meta.get("rate_limit_per_minute"),
            version=meta.get("version", 1),
            tenant_public=meta.get("tenant_public", False),
            idempotent=meta.get("idempotent", False),
            embedding=meta.get("embedding"),
            created_at=meta.get("created_at", ""),
            updated_at=meta.get("updated_at", ""),
        )

        if read.requires_approval or read.risk_level in ("medium", "high"):
            approval_tasks.append({
                "task_id": task["id"],
                "tool_name": read.name,
                "risk_level": read.risk_level,
                "inputs": task.get("inputs", {}),
            })

    if approval_tasks:
        logger.warning(
            "risk_gate.interrupt",
            count=len(approval_tasks),
            tasks=[t["tool_name"] for t in approval_tasks],
        )
        # Build interrupt payload for frontend
        payload = {
            "type": "approval_required",
            "tasks": approval_tasks,
            "question": "The following tools require approval. Approve all?",
        }
        decision: dict[str, Any] = interrupt(payload)
        action = decision.get("action", "approve")
        if action == "reject":
            return {
                "_requires_approval": True,
                "_approval_tasks": [t["task_id"] for t in approval_tasks],
                "_routing_decision": "ask",
                "final_response": "Tool execution was rejected by the user.",
            }
        return {
            "_requires_approval": True,
            "_approval_tasks": [t["task_id"] for t in approval_tasks],
        }

    return {"_requires_approval": False, "_approval_tasks": []}
