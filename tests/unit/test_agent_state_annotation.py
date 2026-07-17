"""Verify AgentState.messages uses the add_messages reducer."""

from typing import get_type_hints

from nexus.agent.state import AgentState


def test_messages_uses_add_messages():
    hints = get_type_hints(AgentState, include_extras=True)
    messages_type = hints["messages"]
    args = getattr(messages_type, "__metadata__", [])
    from langgraph.graph.message import add_messages

    assert add_messages in args, "messages field must use Annotated[..., add_messages]"
