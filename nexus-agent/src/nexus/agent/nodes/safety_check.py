"""safety_and_policy_check — lightweight pre-filter before LLM processing.

Uses deterministic rules (keywords, regex, length limits) to catch:
1. PII / secrets in user messages
2. Prompt injection attempts
3. Out-of-scope / abusive content
4. Empty or near-empty messages

This is NOT a replacement for the LLM's own safety reasoning — it is a
first-pass guard that rejects obviously harmful input before we spend
LLM tokens (and money) on it.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.safety_check")

# Patterns that suggest the user is trying prompt injection
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+|your\s+)?(previous|prior|above)\s+(instructions|prompts|directions)", re.I),
    re.compile(r"forget\s+(everything|all|your)\s+(you\s+)?(were\s+)?(told|instructed)", re.I),
    re.compile(r"(system|admin|sudo)\s*(prompt|override|command)", re.I),
    re.compile(r"you\s+(are|were)\s+(now|actually)\s+(\w+\s+)*?(human|admin|system|dan|jailbroken)", re.I),
    re.compile(r"\[\s*(system|admin|user)\s*\]", re.I),
    re.compile(r"<\s*(system|user|assistant)\s*>", re.I),
]

# PII-like patterns (not exhaustive — flags for review)
_PII_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b\d{16,19}\b"),                          # credit card / PAN
    re.compile(r"\b[A-Z]{2}\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\b"),  # IBAN-like
]

# Content that is out of scope
_OUT_OF_SCOPE_KEYWORDS: list[str] = [
    "write malware", "crack password", "sql injection",
    "bypass security", "hack into", "illegal",
]

_MAX_MESSAGE_LENGTH: int = 32_000


async def safety_and_policy_check(state: AgentState) -> dict[str, Any]:
    """Check the latest user message for safety issues.

    Returns:
        Dict with ``_safety_result`` containing:
        - ``passed`` (bool): whether the message is safe to process
        - ``reason`` (str, optional): why it was rejected
        - ``action`` (str): "reject", "flag", or "allow"
    """
    messages: list = list(state.get("messages", []))
    last_user = ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = str(m.get("content", ""))
            break

    if not last_user.strip():
        return {
            "_safety_result": {"passed": False, "action": "reject", "reason": "Empty message"},
            "final_response": "I didn't receive a message. How can I help you?",
            "_routing_decision": "finalize",
        }

    if len(last_user) > _MAX_MESSAGE_LENGTH:
        return {
            "_safety_result": {"passed": False, "action": "reject", "reason": f"Message too long ({_MAX_MESSAGE_LENGTH} max)"},
            "final_response": "Your message is too long. Please shorten it and try again.",
            "_routing_decision": "finalize",
        }

    # Pattern checks
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(last_user):
            logger.warning("safety_check.injection_pattern", pattern=pattern.pattern[:40])
            return {
                "_safety_result": {
                    "passed": False,
                    "action": "flag",
                    "reason": "Message matches injection pattern. Reviewed by LLM.",
                }
            }

    for pattern in _PII_PATTERNS:
        if pattern.search(last_user):
            logger.info("safety_check.pii_detected", pattern=pattern.pattern[:20])
            return {
                "_safety_result": {
                    "passed": True,
                    "action": "flag",
                    "reason": "Possible PII detected. Flagged for awareness.",
                }
            }

    for keyword in _OUT_OF_SCOPE_KEYWORDS:
        if keyword.lower() in last_user.lower():
            logger.warning("safety_check.out_of_scope", keyword=keyword)
            return {
                "_safety_result": {"passed": False, "action": "reject", "reason": f"Request out of scope."},
                "final_response": "I'm sorry, I can't process that request. It appears to be out of scope.",
                "_routing_decision": "finalize",
            }

    return {
        "_safety_result": {
            "passed": True,
            "action": "allow",
            "reason": "",
        },
    }
