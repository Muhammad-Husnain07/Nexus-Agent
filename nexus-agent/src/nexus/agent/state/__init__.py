"""State models — re-exports AgentState from state_schema for backward compat."""

from nexus.agent.state.context import EntitySet, StructuredContext
from nexus.agent.state_schema import AgentState, _EPHEMERAL_FIELDS

__all__ = [
    "AgentState",
    "EntitySet",
    "StructuredContext",
    "_EPHEMERAL_FIELDS",
]
