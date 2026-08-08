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


class MemoryKind(enum.Enum):
    """Type of stored memory.

    Six-layer model:
    - episodic: event summaries of agent runs
    - semantic: general facts and knowledge
    - procedural: step-by-step how-to sequences
    - task: current workflow scratchpad state
    - project: artifact-bound project-level knowledge
    - user_preference: persistent user choices and corrections
    """

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    TASK = "task"
    PROJECT = "project"
    USER_PREFERENCE = "user_preference"
