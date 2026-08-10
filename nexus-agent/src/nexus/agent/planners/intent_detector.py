"""IntentDetector — deterministic (Tier-1) decomposition of the current
user message into intent units.

Pure syntactic decomposition — no capability names, no domain vocabulary.
The marker set is a CLOSED set of grammatical connectors; everything
semantic (capability matching, aliases) comes from the registry indexes
via ``GlobalContext.match_capabilities``. The LLM-based decomposer (Tier-2,
P4-4) is the rare fallback when this detector's confidence is low.

An intent unit is a clause the user asked for: ``"weather in Lahore"``,
``"exchange rate USD to PKR"``, ``"tell me about Pakistan"``. Negated
units (``don't check the weather``) are flagged so the validator can
FORBID their capabilities; comparison markers and repeated-entity lists
produce instance hints the coverage check uses.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Closed grammatical connector set (syntactic structure, NOT domain logic).
_CONNECTOR_WORDS = re.compile(
    r"(?i)(?<![\w])(?:and|plus|also|then|after|before|but|while|or)(?![\w])"
)
_LIST_AND_RE = re.compile(r"(?i)\b(\d+)\s+and\s+(\d+)\b")
_NEGATION_MARKERS = ("don't", "dont ", " do not ", " not ", " never ", " without ")
_COMPARISON_MARKERS = ("compare", " versus ", "vs", " both ")

# Connector set with WORD BOUNDARIES (B1/P0-B): "or" must never match
# inside "for", "while" never inside "whiles", etc. "&" is normalized to
# " and " before splitting, so it needs no entry here.
_SPLIT_RE = re.compile(r"(?i)(?:,?\s*\b(?:and|plus|also|then|after|before|but|while|or)\b\s+)")
_NEGATION_RE = re.compile(r"(?i)(don't|dont|do not|not|never|without)")
_NUMBER_LIST_RE = re.compile(r"\b\d+\b")

_CONFIDENCE_LOW_THRESHOLD = 0.4


class IntentUnit(BaseModel):
    """A single executable clause of the user request (pure syntax)."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(description="The clause text")
    negated: bool = Field(default=False, description="Negation marker bound to this clause")
    order: int = Field(default=0, description="Position in the request")
    instance_hint: int = Field(default=1, description="Repeated-entity hint (>=2 for comparisons/lists)")
    comparison: bool = Field(default=False, description="Comparison marker present")
    confidence: float = Field(default=1.0, description="Detector confidence for this unit")


class DetectedIntents(BaseModel):
    """Deterministic decomposition result (frozen, pure syntax)."""

    model_config = ConfigDict(frozen=True)

    units: tuple[IntentUnit, ...] = Field(description="Detected intent units")
    confidence: float = Field(description="Overall detector confidence (0-1)")
    source: Literal["deterministic", "llm"] = "deterministic"


class IntentDetector:
    """Deterministic Tier-1 decomposition of the current user message."""

    def detect(self, message: str) -> DetectedIntents:
        """Split the message into intent units.

        Returns a frozen ``DetectedIntents`` — the confidence is low when
        the syntactic split is ambiguous (no connectors but multiple
        entity signals), which triggers the Tier-2 LLM decomposer.
        """
        text = (message or "").strip()
        if not text:
            return DetectedIntents(units=(), confidence=1.0)

        clauses = self._split_clauses(text)
        units: list[IntentUnit] = []
        for order, clause in enumerate(clauses):
            unit = self._build_unit(clause, order)
            if unit.text:
                units.append(unit)

        if not units:
            units.append(self._build_unit(text, 0))

        # Overall confidence: clean multi-clause splits are high-confidence;
        # a single long clause is ambiguous (Tier-2 trigger).
        confidence = 1.0 if len(units) > 1 else 0.9
        if len(units) == 1 and len(text.split()) > 14:
            confidence = 0.6

        return DetectedIntents(units=tuple(units), confidence=confidence)

    @staticmethod
    def _split_clauses(text: str) -> list[str]:
        """Split on grammatical boundaries, preserving numeric lists.

        Clause boundaries: commas, semicolons, em-dashes, and the closed
        connector set. ``"1 and 5"`` (a numeric list) is NOT a boundary —
        it stays inside its clause and raises the instance hint.
        """
        normalized = (
            text.replace("—", ", ").replace("–", ", ").replace(";", ",")
            .replace(":", ", ").replace("&", " and ")
        )
        # List-context "and": protect "1 and 5" style lists from splitting.
        protected: list[tuple[str, str]] = []
        for match in _LIST_AND_RE.finditer(normalized):
            placeholder = f" __list{match.start()}__ "
            protected.append((match.group(0), placeholder.strip()))
            normalized = normalized.replace(match.group(0), placeholder)

        parts = [
            p.strip(" ,.").strip()
            for p in _SPLIT_RE.split(normalized)
            if p.strip(" ,.")
        ]
        for original, placeholder in protected:
            parts = [p.replace(placeholder, original) for p in parts]
        # Comma-separated clauses without connectors: split on ", " too.
        expanded: list[str] = []
        for part in parts:
            expanded.extend(
                p.strip(" ,.").strip()
                for p in part.split(", ")
                if p.strip(" ,.")
            )
        return expanded or [text]

    def _build_unit(self, clause: str, order: int) -> IntentUnit:
        negated = bool(_NEGATION_RE.search(clause))
        comparison = any(m in clause.lower() for m in _COMPARISON_MARKERS)
        numbers = _NUMBER_LIST_RE.findall(clause)
        instance_hint = 1
        if comparison:
            instance_hint = 2
        elif len(numbers) >= 2:
            instance_hint = len(numbers)
        confidence = 1.0 if (negated or comparison or instance_hint > 1) else 0.9
        return IntentUnit(
            text=clause,
            negated=negated,
            order=order,
            instance_hint=instance_hint,
            comparison=comparison,
            confidence=confidence,
        )


def unit_candidates(unit: IntentUnit, gc: Any) -> frozenset[str]:
    """Metadata-driven bridge: the unit's top capability candidates.

    Sources (all registry-derived, never hardcoded): the O(1) keyword map,
    the alias index, the capability-name tokens, and the capability meta's
    own ``keywords``. A unit with NO candidates is UNCLASSIFIABLE — the
    coverage check excludes it (entities like city names are not keywords).
    """
    try:
        from nexus.context.global_context import get_global_context

        gc = gc or get_global_context()
        tokens = re.findall(r"[a-zA-Z]+", unit.text.lower())
        if not tokens:
            return frozenset()
        candidates: set[str] = set()
        # 1. Keyword map (O(1)).
        try:
            candidates.update(gc.match_capabilities(tokens))
        except Exception:
            pass
        # 2. Alias index.
        alias_index = getattr(gc, "alias_index", None) or {}
        for token in tokens:
            for cap in alias_index.get(token, []) or []:
                candidates.add(str(cap))
        # 3. Capability-name tokens + meta keywords.
        index = getattr(gc, "capability_index", None) or {}
        for name, meta in index.items():
            name_tokens = set(re.findall(r"[a-zA-Z]+", str(name).lower()))
            if name_tokens & set(tokens):
                candidates.add(str(name))
                continue
            if isinstance(meta, dict):
                meta_keywords = meta.get("keywords") or []
                if any(str(kw).lower() in tokens for kw in meta_keywords):
                    candidates.add(str(name))
        return frozenset(candidates)
    except Exception:
        return frozenset()
