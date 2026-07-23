"""Format transformers — convert prompts from internal XML to target format.

Each transformer implements transform() which strips or converts XML tags
to the format expected by the target model family. Registered by format name.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger("nexus.llm.format_adapter.transformers")

# Tags that are purely structural and should be stripped for non-XML models
_STRIP_TAGS = {
    "role", "context", "instructions", "thinking_protocol",
    "thinking", "output", "output_format", "rules", "rule",
    "criterion", "step_details", "decision_rules", "available_tools",
    "examples", "common_mistakes", "missing_information", "slot_details",
    "reflection_context", "tool_results", "errors", "when_to_split",
    "when_not_to_split",
}

_XML_TAG_RE = re.compile(r"</?(?:" + "|".join(_STRIP_TAGS) + r")[^>]*>", re.IGNORECASE)
_ALL_TAG_RE = re.compile(r"<[^>]+>", re.IGNORECASE)
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def _strip_xml(text: str, strip_all: bool = False) -> str:
    """Strip XML tags from text."""
    if strip_all:
        text = _ALL_TAG_RE.sub("", text)
    else:
        text = _XML_TAG_RE.sub("", text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def _xml_to_markdown(text: str) -> str:
    """Convert XML-tagged prompts to markdown format."""
    text = _strip_xml(text, strip_all=False)
    # Convert known XML block patterns to markdown
    conversions = [
        (r"<role>\s*(.*?)\s*</role>", r"# Role\n\1"),
        (r"<context>\s*(.*?)\s*</context>", r"## Context\n\1"),
        (r"<instructions>\s*(.*?)\s*</instructions>", r"## Instructions\n\1"),
        (r"<output_format>\s*(.*?)\s*</output_format>", r"## Output Format\n\1"),
        (r"<thinking_protocol>.*?</thinking_protocol>", ""),
        (r"<rule[^>]*>", "- "),
        (r"</rule>", ""),
    ]
    for pattern, replacement in conversions:
        text = re.sub(pattern, replacement, text, flags=re.DOTALL | re.IGNORECASE)
    return _strip_xml(text, strip_all=False)


def _flatten_to_raw(text: str) -> str:
    """Strip ALL markup and return flat text."""
    text = _ALL_TAG_RE.sub("", text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


class _BaseTransformer:
    """Base transformer with common utilities."""

    # True if this transformer passes prompts through unchanged
    is_passthrough: bool = True

    def transform_system(self, text: str) -> str:
        return text

    def transform_user(self, text: str) -> str:
        return text

    def wrap_messages(
        self,
        system: str,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return messages


class PassthroughTransformer(_BaseTransformer):
    """No transformation — pass through as-is (for XML-native models)."""
    pass


class OpenAITransformer(_BaseTransformer):
    """Convert XML prompts to OpenAI-style markdown."""

    is_passthrough: bool = False

    def transform_system(self, text: str) -> str:
        return _xml_to_markdown(text)

    def wrap_messages(self, system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if system:
            return [{"role": "system", "content": system}] + messages
        return messages


class RawTransformer(_BaseTransformer):
    """Strip ALL formatting — concatenate everything into flat text."""

    is_passthrough: bool = False

    def transform_system(self, text: str) -> str:
        return _flatten_to_raw(text)

    def transform_user(self, text: str) -> str:
        return _flatten_to_raw(text)

    def wrap_messages(self, system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        parts = []
        if system:
            parts.append(f"[System]\n{system}")
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"[{role.capitalize()}]\n{content}")
        parts.append("[Assistant]")
        return [{"role": "user", "content": "\n\n".join(parts)}]


class QwenTransformer(_BaseTransformer):
    """Qwen models — pass through XML (they handle it natively)."""
    pass


# ── Registry — add new formats here ────────────────────────────────
# Passthrough formats: anthropic, qwen — handle XML natively
# OpenAI-compatible formats: openai, gemini, deepseek, llama, mistral
# Aggressive strip: raw
FORMAT_TRANSFORMERS: dict[str, _BaseTransformer] = {
    "anthropic": PassthroughTransformer(),
    "openai": OpenAITransformer(),
    "raw": RawTransformer(),
    "qwen": QwenTransformer(),
    "gemini": OpenAITransformer(),
    "deepseek": OpenAITransformer(),
    "llama": OpenAITransformer(),
    "mistral": OpenAITransformer(),
}


def get_transformer(format_name: str) -> _BaseTransformer:
    """Get the transformer for a format name. Falls back to raw."""
    tf = FORMAT_TRANSFORMERS.get(format_name)
    if tf is None:
        logger.warning("format_transformer.unknown", format=format_name, fallback="raw")
        return FORMAT_TRANSFORMERS["raw"]
    return tf
