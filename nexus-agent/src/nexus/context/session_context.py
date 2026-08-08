"""SessionContext — Slow-changing per-session state.

Loaded once per session and updated rarely.  Does NOT travel through
every node transition.  Fields: user_id, policies, long-term memory
references, and registry version checksum.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SessionContext(BaseModel):
    """Slow-changing session-level context.

    Loaded once per session.  Not passed through every node transition.
    Held by the AgentRunner and injected into graph config as needed.

    Attributes:
        session_id: The session UUID.
        user_id: Optional user identifier.
        policies: Policy overrides for this session.
        memory_ids: References to long-term memory entries.
        registry_version_checksum: Registry version at session creation.
    """
    model_config = ConfigDict(extra="forbid")

    session_id: UUID = Field(description="Session identifier")
    user_id: str | None = Field(default=None, description="User identifier")
    policies: dict[str, Any] = Field(
        default_factory=dict,
        description="Policy overrides for this session",
    )
    memory_ids: list[UUID] = Field(
        default_factory=list,
        description="Long-term memory references",
    )
    registry_version_checksum: str = Field(
        default="",
        description="Registry version checksum at session creation",
    )
