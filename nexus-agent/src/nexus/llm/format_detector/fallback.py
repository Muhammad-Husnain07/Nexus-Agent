"""Probe failure fallback — graceful degradation when format detection fails.

Falls back based on:
1. Pattern-based hints in the model string (format hints, NOT hardcoded decisions)
2. Default: 'raw' (strips ALL formatting — works with any model)
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

# Pattern → format hint pairs. These are heuristics, not hard rules.
# The format is still fully configurable via ProviderConfig.prompt_format.
FORMAT_HINTS: list[tuple[str, str]] = [
    ("claude", "anthropic"),
    ("anthropic", "anthropic"),
    ("gemini", "gemini"),
    ("deepseek", "deepseek"),
    ("llama", "llama"),
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
    ("qwen", "qwen"),
]


def get_fallback_format(model: str, failure_reason: str | None = None) -> str:
    """Return the best fallback format when probe fails.

    Uses pattern-based hints from the model name (after provider prefix)
    to guess the format, then falls back to 'raw' which works with any model.
    """
    # Only check the actual model name, not the provider prefix (e.g. "ollama/")
    model_name = model.split("/", 1)[-1].lower()

    for pattern, hint in FORMAT_HINTS:
        if pattern in model_name:
            log.info("format_fallback.using_hint", model=model, hint=hint)
            return hint

    log.warning("format_fallback.default", model=model, reason=failure_reason or "probe_failed")
    return "raw"
