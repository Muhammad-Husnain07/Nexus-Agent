"""Agent error hierarchy — re-exported from central errors module."""

from nexus.errors import (
    AgentError,
    ApprovalRejected,
    ContextWindowExceededError,
    MaxIterationsError,
    PlanningError,
    ToolExecutionError,
)

__all__ = [
    "AgentError",
    "PlanningError",
    "ToolExecutionError",
    "MaxIterationsError",
    "ContextWindowExceededError",
    "ApprovalRejected",
]
