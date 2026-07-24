"""Graph node implementations — one module per node.

Shared helpers for message handling across modules.
"""

from typing import Any

from nexus.agent.nodes.finalize import finalize


def msg_content(msg: Any) -> str:
    """Extract content from either a dict message or a BaseMessage."""
    if isinstance(msg, dict):
        return str(msg.get("content", ""))
    return str(getattr(msg, "content", "") or "")


def msg_role(msg: Any) -> str:
    """Extract role from either a dict message or a BaseMessage."""
    if isinstance(msg, dict):
        return str(msg.get("role", ""))
    role = str(getattr(msg, "type", ""))
    if role == "human":
        return "user"
    if role == "ai":
        return "assistant"
    return role


__all__ = ["finalize", "msg_content", "msg_role"]
