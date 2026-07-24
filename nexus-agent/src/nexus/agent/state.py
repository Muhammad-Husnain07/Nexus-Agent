"""Backward-compat re-exports — new code imports from ``state_schema`` directly.

This module re-exports everything from ``state_schema`` so existing
imports like ``from nexus.agent.state import AgentState`` continue to work.
"""

from nexus.agent.state_schema import (
    AgentState,
    CostTracker,
    EphemeralFlags,
    ExecutionGraph,
    ExecutionNode,
    MessageEntry,
    MessageHistory,
    PersistentContext,
    ToolResult,
    WorkingMemory,
    _EPHEMERAL_FIELDS,
    messages_reducer,
    tool_results_reducer,
)

__all__ = [
    "AgentState",
    "CostTracker",
    "EphemeralFlags",
    "ExecutionGraph",
    "ExecutionNode",
    "MessageEntry",
    "MessageHistory",
    "PersistentContext",
    "ToolResult",
    "WorkingMemory",
    "_EPHEMERAL_FIELDS",
    "messages_reducer",
    "tool_results_reducer",
]
