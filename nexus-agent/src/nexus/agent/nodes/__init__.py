"""Extracted LangGraph node implementations — one module per node.

Shared helpers for message handling across nodes.
"""

from typing import Any


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


from nexus.agent.nodes.analyze_results import analyze_results
from nexus.agent.nodes.dag_expander import dag_expander, route_dag
from nexus.agent.nodes.discover_tools import discover_tools
from nexus.agent.nodes.execute_step import execute_step
from nexus.agent.nodes.finalize import finalize
from nexus.agent.nodes.gather_requirements import gather_requirements
from nexus.agent.nodes.plan import plan
from nexus.agent.nodes.present_preview import present_preview
from nexus.agent.nodes.reflect_on_response import reflect_on_response
from nexus.agent.nodes.respond_without_tool import respond_without_tool
from nexus.agent.nodes.review_final_answer import review_final_answer
from nexus.agent.nodes.review_plan import review_plan
from nexus.agent.nodes.select_and_bind_tools import select_and_bind_tools
from nexus.agent.nodes.tool_executor import tool_executor
from nexus.agent.nodes.understand_intent import understand_intent

__all__ = [
    "understand_intent",
    "gather_requirements",
    "discover_tools",
    "plan",
    "select_and_bind_tools",
    "execute_step",
    "present_preview",
    "analyze_results",
    "dag_expander",
    "route_dag",
    "reflect_on_response",
    "respond_without_tool",
    "review_final_answer",
    "review_plan",
    "tool_executor",
    "finalize",
]
