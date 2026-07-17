"""Complex chat flow: multi-turn with a 5-tool plan and HITL approval gate.

Simulates: discover tools → plan → invoke tool_1 → ... → tool_5 → approve → finalize.
"""

import uuid
from dataclasses import dataclass, field

COMPLEX_FLOW_PROMPT = (
    "Write a draft article about AI trends titled 'The State of AI in 2026', "
    "add it to the Tech category, generate a preview, then publish it."
)


@dataclass
class ComplexFlowMetrics:
    """Track metrics for a single complex-flow execution."""

    ttft_ms: float = 0.0
    total_duration_ms: float = 0.0
    event_count: int = 0
    tool_calls: int = 0
    approval_requests: int = 0
    success: bool = False
    errors: list[str] = field(default_factory=list)


def make_complex_session(tenant_id: str) -> dict:
    """Build a Locust-compatible session payload for a complex chat."""
    return {
        "tenant_id": tenant_id,
        "session_id": str(uuid.uuid4()),
        "message": COMPLEX_FLOW_PROMPT,
        "stream": True,
    }
