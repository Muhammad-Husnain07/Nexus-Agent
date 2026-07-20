"""Python enums mapped to PostgreSQL CHECK-constraint enums via SAEnum."""

from __future__ import annotations

import enum


class SessionStatus(enum.Enum):
    """Conversation session status."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class MessageRole(enum.Enum):
    """Role of a message participant."""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class ToolRiskLevel(enum.Enum):
    """Risk classification for tool execution."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExecutionStatus(enum.Enum):
    """Outcome of a tool execution."""

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    INTERRUPTED = "interrupted"


class AgentRunStatus(enum.Enum):
    """Lifecycle state of an agent run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


class ApprovalStatus(enum.Enum):
    """Human-in-the-loop approval decision."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class MemoryKind(enum.Enum):
    """Type of stored memory."""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    PREFERENCE = "preference"
