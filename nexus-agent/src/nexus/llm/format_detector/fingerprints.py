"""Format fingerprints — regex patterns that identify a model's expected format.

Each fingerprint defines:
- echo_patterns: patterns that SHOULD appear if this format is correct
- exclude_patterns: patterns that should NOT appear if this format is correct
- weight: confidence multiplier

NO model names anywhere — purely pattern-based detection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class FormatFingerprint:
    """Regex patterns that identify a model's expected prompt format."""
    name: str
    echo_patterns: list[re.Pattern] = field(default_factory=list)
    exclude_patterns: list[re.Pattern] = field(default_factory=list)
    weight: float = 1.0


FINGERPRINTS: dict[str, FormatFingerprint] = {
    "anthropic": FormatFingerprint(
        name="anthropic",
        echo_patterns=[
            re.compile(r"<probe>\s*ok\s*</probe>", re.IGNORECASE),
        ],
        weight=1.0,
    ),
    "qwen": FormatFingerprint(
        name="qwen",
        echo_patterns=[
            re.compile(r"<probe>\s*ok\s*</probe>", re.IGNORECASE),
            re.compile(r"<\|im_start\|>", re.IGNORECASE),
        ],
        weight=0.9,
    ),
    "openai": FormatFingerprint(
        name="openai",
        echo_patterns=[
            re.compile(r"\*\*probe\*\*|\*\*ok\*\*", re.IGNORECASE),
            re.compile(r"\"ok\"", re.IGNORECASE),
        ],
        exclude_patterns=[
            re.compile(r"<probe>", re.IGNORECASE),
        ],
        weight=0.9,
    ),
    "gemini": FormatFingerprint(
        name="gemini",
        echo_patterns=[
            re.compile(r"\*{1,2}ok\*{1,2}", re.IGNORECASE),
            re.compile(r"#probe", re.IGNORECASE),
        ],
        exclude_patterns=[
            re.compile(r"<probe>", re.IGNORECASE),
        ],
        weight=0.85,
    ),
    "deepseek": FormatFingerprint(
        name="deepseek",
        echo_patterns=[
            re.compile(r"\bprobe\b", re.IGNORECASE),
        ],
        exclude_patterns=[
            re.compile(r"<probe>", re.IGNORECASE),
            re.compile(r"\*{2}", re.IGNORECASE),
        ],
        weight=0.8,
    ),
    "llama": FormatFingerprint(
        name="llama",
        echo_patterns=[
            re.compile(r"^ok$", re.IGNORECASE | re.MULTILINE),
            re.compile(r"\"ok\"", re.IGNORECASE),
        ],
        exclude_patterns=[
            re.compile(r"<[^>]+>", re.IGNORECASE),
            re.compile(r"\*+", re.IGNORECASE),
        ],
        weight=0.7,
    ),
    "mistral": FormatFingerprint(
        name="mistral",
        echo_patterns=[
            re.compile(r"^ok$", re.IGNORECASE | re.MULTILINE),
            re.compile(r"ok\.?", re.IGNORECASE),
        ],
        exclude_patterns=[
            re.compile(r"<[^>]+>", re.IGNORECASE),
            re.compile(r"\*+", re.IGNORECASE),
        ],
        weight=0.7,
    ),
    "raw": FormatFingerprint(
        name="raw",
        echo_patterns=[
            re.compile(r"^(?:probe[:\s]+)?ok\s*$", re.IGNORECASE | re.MULTILINE),
        ],
        exclude_patterns=[
            re.compile(r"<[^>]+>", re.IGNORECASE),
            re.compile(r"\*{2}", re.IGNORECASE),
        ],
        weight=0.6,
    ),
}
