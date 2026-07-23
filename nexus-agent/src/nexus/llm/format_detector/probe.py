"""Probe message for runtime format detection.

Sends a minimal message containing XML tags to see if the model
echoes them (XML-native) or strips them (markdown/raw).
Tiny cost: ~1 input token, 10 max output tokens.
"""

PROBE_MESSAGE = [
    {
        "role": "user",
        "content": "Reply with EXACTLY: <probe>ok</probe>. Nothing else.",
    },
]

PROBE_KWARGS = {
    "max_tokens": 10,
    "temperature": 0.0,
}
