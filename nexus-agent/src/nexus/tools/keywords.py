"""Keyword extraction engine — single source of truth for tool keyword generation.

ZERO hardcoded word lists. Keywords come EXCLUSIVELY from the
operator-declared identifier metadata of the tool:
- the tool NAME (identifier tokens),
- its TAGS (as-is),
- its ALIASES (kept verbatim — the exact trigger phrases users say).

Free-form prose (descriptions/purposes) is deliberately NOT a keyword source,
and aliases are never tokenized into single words: both would introduce
non-discriminative function words, and filtering those requires a hardcoded
stopword list (prohibited). The operator declares intent precisely via
aliases/explicit keywords.
"""

from __future__ import annotations


def extract_keywords(
    name: str,
    purpose: str = "",
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
    skip_prefixes: set[str] | None = None,
) -> list[str]:
    """Extract deduplicated, sorted keyword list from tool metadata.

    Sources (in order of weight), all data-driven from the tool's own
    registration metadata — operator-declared identifiers only:
    1. **Name tokens** — split on ``_``
    2. **Tags** — added as-is
    3. **Aliases** — added verbatim (operator-declared trigger phrases)

    Free-form prose (``purpose``) is NOT tokenized: it is the source of
    non-discriminative function words, and filtering them would require a
    hardcoded word list (prohibited). The operator declares the tool's
    trigger vocabulary precisely via aliases (and explicit ``keywords``
    during registration); the aliases are the exact phrases users say.

    Args:
        name: Tool name (e.g. ``get_weather``).
        purpose: Natural-language description (kept for backward
            compatibility — NOT a keyword source).
        tags: List of categorization tags.
        aliases: List of alternative names or phrases.
        skip_prefixes: Optional caller-provided prefixes to strip
            (default: none — nothing is filtered implicitly).

    Returns:
        Sorted deduplicated list of keywords.
    """
    skip = frozenset(skip_prefixes) if skip_prefixes else frozenset()

    seen: set[str] = set()
    keywords: list[str] = []

    def _add(word: str) -> None:
        w = word.lower().strip()
        if w not in seen and len(w) > 2:
            seen.add(w)
            keywords.append(w)

    _add(name)

    for part in name.lower().split("_"):
        if part not in skip:
            _add(part)

    for tag in (tags or []):
        if isinstance(tag, str):
            _add(tag)

    # Aliases are OPERATOR-DECLARED trigger phrases ("studio ghibli
    # movies", "what can i cook") — kept VERBATIM as keywords, never
    # tokenized into single words (tokenizing a natural-language phrase
    # would re-introduce the non-discriminative function words that
    # hardcoded stopword lists exist to remove — prohibited). The
    # retrieval matches keyword phrases against the query as phrases.
    for alias in (aliases or []):
        if isinstance(alias, str) and alias.strip():
            _add(alias)

    keywords.sort()
    return keywords
