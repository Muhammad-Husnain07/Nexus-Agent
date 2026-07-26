"""Keyword extraction engine — single source of truth for tool keyword generation.

All NLP lists (stop words, skip prefixes) are loaded from ``settings.agent``.
Zero hardcoded NLP lists.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def _load_stop_words() -> frozenset[str]:
    """Load stop words from settings.agent.stop_words, fall back to empty."""
    try:
        from nexus.config.settings import get_settings
        return frozenset(get_settings().agent.stop_words)
    except Exception:
        return frozenset()


def _load_skip_prefixes() -> set[str]:
    """Load skip prefixes from settings.agent.skip_prefixes, fall back to empty."""
    try:
        from nexus.config.settings import get_settings
        return set(get_settings().agent.skip_prefixes)
    except Exception:
        return {"get", "search", "predict", "find", "list", "fetch",
                "create", "update", "delete", "patch", "put", "post", "echo"}


_STOP_WORDS: frozenset[str] = _load_stop_words()


def tokenize(text: str) -> list[str]:
    """Lowercase, unicode-normalize, strip punctuation, tokenize, remove stop words."""
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = text.split()
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


def extract_keywords(
    name: str,
    purpose: str = "",
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
    skip_prefixes: set[str] | None = None,
) -> list[str]:
    """Extract deduplicated, sorted keyword list from tool metadata.

    Sources (in order of weight):
    1. **Name tokens** — split on ``_``, filter skip prefixes + stop words
    2. **Purpose tokens** — extract meaningful words from description
    3. **Tags** — added as-is
    4. **Aliases** — tokenized and added as-is

    Args:
        name: Tool name (e.g. ``get_weather``).
        purpose: Natural-language description of tool usage.
        tags: List of categorization tags.
        aliases: List of alternative names or phrases.
        skip_prefixes: Action verb prefixes to strip (default: from settings).

    Returns:
        Sorted deduplicated list of keywords.
    """
    if skip_prefixes is None:
        skip_prefixes = _load_skip_prefixes()

    seen: set[str] = set()
    keywords: list[str] = []

    def _add(word: str) -> None:
        w = word.lower().strip()
        if w not in seen and len(w) > 2 and w not in _STOP_WORDS:
            seen.add(w)
            keywords.append(w)

    _add(name)

    for part in name.lower().split("_"):
        if part not in skip_prefixes:
            _add(part)

    if purpose:
        for token in tokenize(purpose):
            _add(token)

    for tag in (tags or []):
        if isinstance(tag, str):
            _add(tag)

    for alias in (aliases or []):
        for token in tokenize(alias):
            _add(token)

    keywords.sort()
    return keywords
