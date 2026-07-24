"""Keyword extraction engine — single source of truth for tool keyword generation.

Usage::

    from nexus.tools.keywords import extract_keywords

    keywords = extract_keywords(
        name="get_weather",
        purpose="Use when the user asks about weather, temperature, or conditions",
        tags=["weather", "data", "forecast"],
        aliases=["rain", "umbrella", "outside weather"],
    )
    # Returns: ["forecast", "get_weather", "outside", "rain", "temperature",
    #           "umbrella", "weather", "conditions", "data"]
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "is", "it", "of", "in", "on", "for", "to", "with",
    "and", "or", "but", "not", "use", "when", "about", "that", "this",
    "from", "as", "at", "by", "be", "are", "was", "were", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "can", "could", "should", "may", "might", "shall", "need",
})


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
        skip_prefixes: Action verb prefixes to strip (default: common ones).

    Returns:
        Sorted deduplicated list of keywords.
    """
    if skip_prefixes is None:
        skip_prefixes = {"get", "search", "predict", "find", "list", "fetch",
                         "create", "update", "delete", "patch", "put", "post", "echo"}

    seen: set[str] = set()
    keywords: list[str] = []

    def _add(word: str) -> None:
        w = word.lower().strip()
        if w not in seen and len(w) > 2 and w not in _STOP_WORDS:
            seen.add(w)
            keywords.append(w)

    # 1. Full name (exact match weight: 5)
    _add(name)

    # 2. Name tokens (split on underscore)
    for part in name.lower().split("_"):
        if part not in skip_prefixes:
            _add(part)

    # 3. Purpose tokens
    if purpose:
        for token in tokenize(purpose):
            _add(token)

    # 4. Tags
    for tag in (tags or []):
        if isinstance(tag, str):
            _add(tag)

    # 5. Aliases — tokenize each
    for alias in (aliases or []):
        for token in tokenize(alias):
            _add(token)

    keywords.sort()
    return keywords
