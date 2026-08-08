"""Layered capability resolution — deterministic, metadata-driven.

Resolves an LLM-produced operation name onto the registered capability
catalog with a strict, layered pipeline:

    L1  exact          ``logical_op_name ==`` (no tolerance)
    L2  domain         domain hint narrows the candidate space first
    L3  alias          explicit operator-declared aliases (O(1))
    L4  fuzzy          RapidFuzz over the domain-scoped catalog
                        (configurable scorer, threshold — never below)
    L5  llm_repair     (caller-driven) top-K candidates only

Every resolution returns a ``ResolutionResult`` carrying the matched layer,
confidence, and elapsed time — full observability, no guessing below the
configured threshold. No capability, tool, or domain is hardcoded: the
candidate set, aliases, and domains all come from the live registry.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.capabilities.resolution")

# Resolution layers, in priority order (exposed for tests + telemetry).
LAYER_EXACT = "exact"
LAYER_DOMAIN = "domain"
LAYER_ALIAS = "alias"
LAYER_FUZZY = "fuzzy"
LAYER_FAILED = "failed"

_VALID_LAYERS = frozenset({LAYER_EXACT, LAYER_DOMAIN, LAYER_ALIAS, LAYER_FUZZY, LAYER_FAILED})


@dataclass(frozen=True)
class ResolutionResult:
    """Outcome of resolving one operation name onto the catalog.

    Attributes:
        op: The resolved capability name (``None`` when unresolved).
        layer: Which layer produced the match (exact|domain|alias|fuzzy|failed).
        confidence: 0-100 confidence of the match.
        elapsed_ms: Resolution latency in milliseconds.
        domain_hint: Optional domain used to narrow the search.
        candidates: Top candidate names considered (for debugging).
    """

    op: str | None
    layer: str = LAYER_FAILED
    confidence: float = 0.0
    elapsed_ms: float = 0.0
    domain_hint: str | None = None
    candidates: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Serialise for events/telemetry."""
        return {
            "op": self.op,
            "layer": self.layer,
            "confidence": self.confidence,
            "elapsed_ms": self.elapsed_ms,
            "domain_hint": self.domain_hint,
            "candidates": list(self.candidates[:10]),
        }


def _normalize(name: str) -> str:
    """Normalize a name for comparison: lowercase, alphanumeric only.

    Unicode-normalized (NFKD) so accented characters collapse to ASCII.
    """
    import re as _re
    import unicodedata as _ud

    normalized = _ud.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    return _re.sub(r"[^a-z0-9]", "", normalized.lower())


def _fuzzy_scorer() -> Any:
    """Return the configured RapidFuzz scorer callable."""
    from rapidfuzz import fuzz

    scorer_name = get_settings().resolver.fuzzy_scorer
    return {
        "ratio": fuzz.ratio,
        "token_sort": fuzz.token_sort_ratio,
        "token_set": fuzz.token_set_ratio,
        "wratio": fuzz.WRatio,
    }.get(scorer_name, fuzz.WRatio)


def _fuzzy_threshold() -> float:
    """Return the fuzzy match threshold (0-100) from settings."""
    try:
        return float(get_settings().resolver.fuzzy_threshold)
    except Exception:
        return 95.0


def fuzzy_best_match(
    query: str,
    choices: list[str],
    threshold: float | None = None,
) -> tuple[str, float] | None:
    """Return the best RapidFuzz match for ``query`` against ``choices``.

    Uses ``rapidfuzz.process.extractOne`` with the configured scorer. Returns
    ``None`` when the best score is below ``threshold`` (default from
    settings, 95) — the caller must NEVER execute below the threshold.

    Args:
        query: The string to match.
        choices: Candidate strings (e.g. capability names).
        threshold: Minimum score (0-100) to accept; None = settings default.

    Returns:
        ``(best_choice, score)`` or ``None`` when below threshold.
    """
    if not query or not choices:
        return None
    try:
        from rapidfuzz import process

        result = process.extractOne(
            query,
            choices,
            scorer=_fuzzy_scorer(),
        )
    except Exception as exc:
        logger.warning("resolution.fuzzy_failed", error=str(exc)[:200])
        return None
    if result is None:
        return None
    best, score, _index = result
    limit = threshold if threshold is not None else _fuzzy_threshold()
    if score < limit:
        return None
    return str(best), float(score)


def alias_lookup(alias: str, alias_index: dict[str, str]) -> str | None:
    """O(1) exact alias → capability lookup.

    Only explicit operator-declared aliases live in ``alias_index`` — a
    keyword or fuzzy candidate is never treated as an alias match.
    """
    if not alias:
        return None
    direct = alias_index.get(alias)
    if direct is not None:
        return direct
    return alias_index.get(_normalize(alias))


def alias_token_match(
    requested: str,
    alias_index: dict[str, str],
) -> str | None:
    """Resolve via token-overlap against explicit aliases.

    The LLM often reorders or prefixes alias words (e.g. the alias
    ``"pokemon info"`` and the LLM output ``"get_pokemon_info"`` share the
    tokens {pokemon, info}). For every explicit alias whose normalized
    tokens are a subset of the requested name's tokens, return the mapped
    capability. Exact alias lookups still win (checked first by callers).

    Args:
        requested: The LLM-produced operation name.
        alias_index: Explicit alias → capability map.

    Returns:
        The mapped capability name, or ``None`` when no alias token-overlap.
    """
    if not requested or not alias_index:
        return None
    req_tokens = set(_tokenize_words(requested))
    if not req_tokens:
        return None
    for alias, cap in alias_index.items():
        alias_tokens = set(_tokenize_words(alias))
        if not alias_tokens:
            continue
        if alias_tokens <= req_tokens:
            return cap
    return None


def _tokenize_words(name: str) -> list[str]:
    """Split a name into lowercase tokens (underscores/spaces/case).

    Unicode-normalized (NFKD) so accented characters (e.g. the LLM's
    ``pokémon``) collapse to ASCII and still match.
    """
    import re as _re
    import unicodedata as _ud

    normalized = _ud.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    return [
        t for t in _re.findall(r"[a-z0-9]+", normalized.lower()) if len(t) > 1
    ]


def resolve_operation(
    requested: str,
    *,
    alias_index: dict[str, str] | None = None,
    domain_index: dict[str, list[str]] | None = None,
    domain_hint: str | None = None,
    catalog: list[str] | None = None,
    fuzzy_threshold: float | None = None,
) -> ResolutionResult:
    """Resolve an operation name through the layered pipeline.

    Args:
        requested: The operation name (LLM output or plan reference).
        alias_index: GlobalContext alias map (alias → canonical op).
        domain_index: GlobalContext domain map (domain → [ops]).
        domain_hint: Optional domain to narrow the candidate space.
        catalog: Full candidate op list (falls back to alias/domain maps).
        fuzzy_threshold: Fuzzy acceptance threshold (None = settings).

    Returns:
        A ``ResolutionResult`` — never raises; ``op=None`` + layer=failed
        means the caller must invoke LLM repair (top-K) or surface an error.
    """
    started = time.perf_counter()

    def _done(op: str | None, layer: str, confidence: float, candidates: list[str]) -> ResolutionResult:
        return ResolutionResult(
            op=op,
            layer=layer,
            confidence=confidence,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            domain_hint=domain_hint,
            candidates=tuple(candidates),
        )

    if not requested:
        return _done(None, LAYER_FAILED, 0.0, [])

    # L1 — exact (no tolerance)
    if catalog and requested in catalog:
        return _done(requested, LAYER_EXACT, 100.0, [requested])

    # L2 — domain narrowing
    scoped: list[str] | None = None
    if domain_hint and domain_index:
        scoped = domain_index.get(domain_hint) or domain_index.get(_normalize(domain_hint))
    if scoped:
        if requested in scoped:
            return _done(requested, LAYER_DOMAIN, 100.0, scoped)
    candidates = list(scoped) if scoped else list(catalog or [])

    # L3 — explicit alias (O(1) exact, then token-overlap for reordered
    # LLM names like "get_pokemon_info" matching the alias "pokemon info").
    if alias_index:
        matched = alias_lookup(requested, alias_index)
        if matched is None:
            matched = alias_token_match(requested, alias_index)
        if matched is not None:
            if not candidates or matched in candidates:
                return _done(matched, LAYER_ALIAS, 100.0, candidates)
            return _done(matched, LAYER_ALIAS, 100.0, candidates + [matched])

    # L4 — RapidFuzz (domain-scoped when available, NEVER below threshold)
    if candidates:
        best = fuzzy_best_match(requested, candidates, threshold=fuzzy_threshold)
        if best is not None:
            choice, score = best
            return _done(choice, LAYER_FUZZY, score, candidates)

    return _done(None, LAYER_FAILED, 0.0, candidates)
