"""Simple chat flow: 1 turn, 1 tool call — models a basic Q&A."""

import uuid
from dataclasses import dataclass, field

SIMPLE_FLOW_PROMPT = "List all articles in the Tech category."


@dataclass
class SimpleFlowMetrics:
    """Track metrics for a single simple-flow execution."""

    ttft_ms: float = 0.0  # time to first SSE event
    total_duration_ms: float = 0.0
    event_count: int = 0
    tool_calls: int = 0
    success: bool = False
    errors: list[str] = field(default_factory=list)


def make_simple_session(tenant_id: str) -> dict:
    """Build a Locust-compatible session payload for a simple chat."""
    return {
        "tenant_id": tenant_id,
        "session_id": str(uuid.uuid4()),
        "message": SIMPLE_FLOW_PROMPT,
        "stream": True,
    }
