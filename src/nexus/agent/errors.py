"""Agent error hierarchy for the LangGraph orchestration layer."""

from __future__ import annotations


class AgentError(Exception):
    """Base exception for all agent-level errors."""


class PlanningError(AgentError):
    """Raised when the LLM fails to produce a valid plan."""


class ToolExecutionError(AgentError):
    """Raised when a tool call fails unexpectedly during execution."""


class MaxIterationsError(AgentError):
    """Raised when the agent exceeds ``max_iterations`` without finalizing."""


class ContextWindowExceededError(AgentError):
    """Raised when the conversation exceeds the token budget."""


class ApprovalRejected(AgentError):
    """Raised when a human rejects a tool call during HITL."""
