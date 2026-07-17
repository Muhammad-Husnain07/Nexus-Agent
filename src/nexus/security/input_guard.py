"""Prompt injection and output leakage guards.

Scans user messages for known injection patterns and agent responses
for leaked secrets/PII.  Uses regex matching with an optional Presidio
integration stub for PII detection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger("nexus.security.input_guard")

# ---------------------------------------------------------------------------
# Common injection patterns
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[tuple[str, str]] = [
    # Direct instruction override
    (
        "ignore_previous",
        r"(?i)(ignore|disregard|forget|override|bypass)\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|directives|commands|rules)",
    ),
    (
        "system_prompt_leak",
        r"(?i)(your\s+)?(system\s+)?(prompt|instructions|directive)\s*(:|=|is|was|tell|give|reveal|show|what)?",
    ),
    (
        "system_prompt_query",
        r"(?i)(what\s+(is|are)\s+(your\s+)?(system\s+)?(prompt|instructions|directive))",
    ),
    (
        "role_play_override",
        r"(?i)(you\s+are\s+(now|no\s+longer)|act\s+as\s+if|pretend\s+(that\s+)?you)\s+(?!.*(assistant|helpful|ai))",
    ),
    ("dan_mode", r"(?i)(do\s+anything\s+now|jailbreak|dan\s*mode|developer\s*mode)"),
    ("injected_context", r"(?i)(the\s+following\s+is\s+(an?\s+)?(instruction|directive|command))"),
    (
        "output_formatting",
        r"(?i)(output\s+(only|exclusively|just)\s+(json|xml|yaml)|respond\s+with\s+(json|xml))",
    ),
    (
        "ignore_constraints",
        r"(?i)(ignore\s+(your\s+)?(constraints|boundaries|limitations|safeguards|ethics|guidelines))",
    ),
]

# ---------------------------------------------------------------------------
# PII / secret patterns
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[tuple[str, str]] = [
    ("email", r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    (
        "api_key_generic",
        r"(?i)(api[_-]?key|apikey|api_secret|secret\s*key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}",
    ),
    ("nxs_api_key", r"nxs_[A-Za-z0-9\-_]{32,}"),
    ("bearer_token", r"(?i)bearer\s+[A-Za-z0-9\-._~+/]{20,}"),
    ("credit_card", r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b"),
    ("aws_key", r"(?i)AKIA[0-9A-Z]{16}"),
    ("private_key_header", r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),
]

# ---------------------------------------------------------------------------
# Hidden unicode characters
# ---------------------------------------------------------------------------

_HIDDEN_UNICODE: list[int] = list(range(0x200B, 0x200F)) + [
    0xFEFF,
    0x00AD,
    0x2060,
    0x2061,
    0x2062,
    0x2063,
    0x2064,
]


# ---------------------------------------------------------------------------
# Scan results
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    """Result of scanning text for injection or PII patterns."""

    flagged: bool = False
    reason: str = ""
    matched_patterns: list[dict[str, Any]] = field(default_factory=list)
    sanitized: str | None = None


# ---------------------------------------------------------------------------
# PromptInjectionGuard
# ---------------------------------------------------------------------------


class PromptInjectionGuard:
    """Scans user messages for prompt injection patterns.

    Usage::

        guard = PromptInjectionGuard()
        result = guard.scan(user_message)
        if result.flagged:
            logger.warning("injection.detected", reason=result.reason)
    """

    def __init__(self, patterns: list[tuple[str, str]] | None = None) -> None:
        self._patterns = patterns or _INJECTION_PATTERNS
        self._hidden_re = re.compile("[" + "".join(chr(c) for c in _HIDDEN_UNICODE) + "]")

    def scan(self, text: str, sanitize: bool = False) -> ScanResult:
        """Scan *text* for injection patterns.

        Args:
            text: The user message or tool response to scan.
            sanitize: If True, return a sanitized version with matching
                patterns removed.

        Returns:
            A ``ScanResult`` with findings.
        """
        result = ScanResult()

        # Check for hidden unicode
        hidden_matches = list(self._hidden_re.finditer(text))
        if hidden_matches:
            result.flagged = True
            result.reason = "Hidden unicode characters detected"
            result.matched_patterns.append(
                {
                    "pattern": "hidden_unicode",
                    "count": len(hidden_matches),
                    "positions": [m.start() for m in hidden_matches[:5]],
                }
            )
            if sanitize:
                result.sanitized = self._hidden_re.sub("", text)

        # Check injection patterns
        for name, pattern in self._patterns:
            matches = list(re.finditer(pattern, text))
            if matches:
                result.flagged = True
                if not result.reason:
                    result.reason = f"Matched injection pattern: {name}"
                result.matched_patterns.append(
                    {
                        "pattern": name,
                        "count": len(matches),
                        "sample": matches[0].group()[:100],
                    }
                )

        return result


# ---------------------------------------------------------------------------
# OutputGuard
# ---------------------------------------------------------------------------


class OutputGuard:
    """Scans agent responses for leaked secrets or PII before sending to the user.

    Usage::

        guard = OutputGuard()
        result = guard.scan(agent_response)
        if result.flagged:
            # Redact or block the response
            ...
    """

    def __init__(self, patterns: list[tuple[str, str]] | None = None) -> None:
        self._patterns = patterns or _PII_PATTERNS

    def scan(self, text: str, redact: bool = False) -> ScanResult:
        """Scan *text* for leaked secrets or PII.

        Args:
            text: The agent response to scan.
            redact: If True, replace matched content with ``[REDACTED]``.

        Returns:
            A ``ScanResult`` with findings.
        """
        result = ScanResult()
        sanitized = text if redact else None

        for name, pattern in self._patterns:
            matches = list(re.finditer(pattern, text))
            if matches:
                result.flagged = True
                if not result.reason:
                    result.reason = f"Matched PII/secret pattern: {name}"
                result.matched_patterns.append(
                    {
                        "pattern": name,
                        "count": len(matches),
                    }
                )
                if redact:
                    sanitized = re.sub(pattern, "[REDACTED]", sanitized or text)

        if redact:
            result.sanitized = sanitized
        return result

    # ------------------------------------------------------------------
    # Presidio integration stub
    # ------------------------------------------------------------------

    @staticmethod
    def analyze_with_presidio(text: str) -> list[dict[str, Any]]:
        """Stub for Microsoft Presidio PII detection.

        Replace this with actual Presidio ``AnalyzerEngine`` calls:

        .. code-block:: python

            from presidio_analyzer import AnalyzerEngine
            engine = AnalyzerEngine()
            results = engine.analyze(text=text, language="en")
            return [
                {"entity": r.entity_type, "score": r.score, "start": r.start, "end": r.end}
                for r in results
            ]

        Returns:
            Empty list (stub).
        """
        return []
