"""Configurable JSON extractor for LLM outputs — no hardcoded strategies.

Supports a pipeline of extraction strategies defined via settings.
Strategies are tried in order; the first that returns valid JSON wins.

Default strategy pipeline:
1. ``output_tags`` — extract JSON from ``<output>...</output>`` blocks
2. ``brace_counting`` — find first complete ``{...}`` via depth counting
3. ``json5`` — fallback to lenient JSON5 parsing (string fallback)
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.utils.json_extractor")

_OUTPUT_TAG_RE = re.compile(r"<output>\s*(\{[\s\S]*?\})\s*(?:</output>|<output>)?")
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def _strategy_output_tags(content: str) -> str | None:
    """Extract JSON from <output> tags — fast path for well-behaved models."""
    match = _OUTPUT_TAG_RE.search(content)
    if match:
        return match.group(1).strip()
    return None


def _strategy_brace_counting(content: str) -> str | None:
    """Find the first complete JSON object via brace-depth counting.

    Handles run-on generation, malformed tags, and multiple JSON objects.
    Only returns the content up to the matching closing brace.
    """
    depth = 0
    start = -1
    for i, ch in enumerate(content):
        if ch == "{":
            if start < 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                return content[start:i + 1]
    return None


def _strategy_json5(content: str) -> str | None:
    """Fallback: try to parse with json5 (more lenient)."""
    try:
        import json5 as _json5  # noqa: PLC0415
        _json5.loads(content)
        return content  # It's valid json5 — return as-is
    except Exception:
        pass
    return None


_STRATEGIES: dict[str, Any] = {
    "output_tags": _strategy_output_tags,
    "brace_counting": _strategy_brace_counting,
    "json5": _strategy_json5,
}

_DEFAULT_PIPELINE = ["output_tags", "brace_counting", "json5"]


class JsonExtractor:
    """Configurable JSON extraction pipeline with strategy-based fallbacks.

    Usage::

        extractor = JsonExtractor()
        result = extractor.extract(raw_llm_output)

    The strategy pipeline is loaded from settings on first use and cached.
    """

    def __init__(self, pipeline: list[str] | None = None) -> None:
        self._pipeline: list[str] | None = pipeline

    def _get_pipeline(self) -> list[str]:
        """Return the strategy pipeline from settings or default."""
        if self._pipeline is not None:
            return self._pipeline
        try:
            pipeline = getattr(get_settings().tools, "json_extraction_pipeline", None)
            if pipeline and isinstance(pipeline, list):
                return pipeline
        except Exception:
            pass
        return list(_DEFAULT_PIPELINE)

    def _preprocess(self, content: str) -> str:
        """Strip tags that commonly interfere with JSON extraction.

        Tags to strip are loaded from settings -> ``json_extraction_strip_tags``.
        """
        try:
            strip_tags = getattr(get_settings().tools, "json_extraction_strip_tags", None)
            if strip_tags and isinstance(strip_tags, list):
                for tag in strip_tags:
                    pattern = f"</?{tag}>"
                    content = re.sub(pattern, "", content, flags=re.IGNORECASE)
                return content
        except Exception:
            pass
        # Default: strip common interfering tags
        content = re.sub(r"</?thinking>|</?think>|</?output>", "", content, flags=re.IGNORECASE)
        return content

    def extract(self, content: str) -> str:
        """Extract a JSON string from LLM output using the configured pipeline.

        Each strategy is tried in order.  If a strategy returns something
        that parses as valid JSON, it is returned immediately.
        If all strategies fail, the original content is returned.

        Args:
            content: Raw LLM output text.

        Returns:
            A valid JSON string, or the original content if extraction fails.
        """
        if not content or not content.strip():
            return content

        # Fast path: try each strategy on the raw content
        for strategy_name in self._get_pipeline():
            fn = _STRATEGIES.get(strategy_name)
            if fn is None:
                continue
            try:
                candidate = fn(content)
                if candidate is not None and candidate.strip():
                    # Validate it's parseable JSON
                    json.loads(candidate)
                    return candidate
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        # Fallback: preprocess (strip tags) then try pipeline again
        cleaned = self._preprocess(content)
        if cleaned != content:
            for strategy_name in self._get_pipeline():
                fn = _STRATEGIES.get(strategy_name)
                if fn is None:
                    continue
                try:
                    candidate = fn(cleaned)
                    if candidate is not None and candidate.strip():
                        json.loads(candidate)
                        return candidate
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue

        # Last resort: markdown code fence + greedy JSON
        try:
            fence = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content)
            if fence:
                json.loads(fence.group(1))
                return fence.group(1)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        # Absolute last resort: greedy JSON match
        match = _JSON_OBJECT_RE.search(content)
        if match:
            try:
                json.loads(match.group(0))
                return match.group(0)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        return content

    def extract_parsed(self, content: str) -> dict[str, Any] | list[Any] | None:
        """Extract and parse JSON from LLM output.

        Returns a Python dict/list, or ``None`` if extraction fails.
        """
        result = self.extract(content)
        if not result:
            return None
        try:
            return json.loads(result)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None


# Singleton for convenience
extractor = JsonExtractor()
"""Default singleton JsonExtractor instance."""
