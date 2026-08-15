"""Graph node implementations — one module per node.

Shared helpers for message handling across modules.
"""

from typing import Any

from nexus.agent.nodes.validation_node import validation_node, validation_result_as_string


def msg_content(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("content", ""))
    return str(getattr(msg, "content", "") or "")


def msg_role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role", ""))
    role = str(getattr(msg, "type", ""))
    if role == "human":
        return "user"
    if role == "ai":
        return "assistant"
    return role


__all__ = [
    "finalize",
    "msg_content",
    "msg_role",
    "validation_node",
    "validation_result_as_string",
    "clarification_node",
]
