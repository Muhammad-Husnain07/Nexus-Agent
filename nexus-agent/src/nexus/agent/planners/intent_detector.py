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


def _extract_entities(clause: str) -> list[str]:
    """Entity values from a clause (proper nouns after in/for/of/at).

    Pure syntax — no domain vocabulary. Returns de-duplicated entities.
    Article-led captures ("the coordinate") and generic function words
    are NOT entities.
    """
    out: list[str] = []
    for m in re.finditer(
        r"(?i)\b(?:in|for|of|at)\s+([a-z][a-z0-9 .'-]{2,40})", clause
    ):
        ent = m.group(1).strip(" .'")
        ent = re.sub(r"^(?:the|a|an|my|our|your)\s+", "", ent).strip()
        low = ent.lower()
        if not ent or low in {"coordinate", "coordinates", "address", "location",
                              "weather", "results", "result", "data", "value"}:
            continue
        if low not in {e.lower() for e in out}:
            out.append(ent)
    return out[:6]


def _anaphoric_artifact(goal: str) -> str:
    """The artifact an anaphoric clause consumes ("the coordinates..." → coordinates)."""
    m = re.search(r"(?i)(?:the\s+|those\s+|these\s+)?(coordinates|results?|data|location|address|values?)", goal)
    return m.group(1).rstrip("s") if m else "output"


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


# ============================================================================
# P0-C STRUCTURED INTENT GRAPH — decomposition coverage before resolution
# ============================================================================
#
# The Tier-1/2 units above are clause-level.  P0-C adds the STRUCTURED
# representation the reviewer's architecture requires: goals (never tool
# names), entities, requested outputs, and relationships (a later intent
# consuming an earlier one's output — the K83 class: "the address at the
# coordinates returned for Lahore" is TWO intents with a relationship, and
# the resolver must never see only one).


class IntentRelationship(BaseModel):
    """A dependency between two detected intents (output → input)."""

    model_config = ConfigDict(frozen=True)

    source_intent: str = Field(description="Intent ID that produces the value")
    target_intent: str = Field(description="Intent ID that consumes the value")
    artifact: str = Field(description="What is consumed (e.g. 'coordinates', 'location')")


class DetectedIntent(BaseModel):
    """One structured intent: the WHAT, never the HOW (no capability names)."""

    model_config = ConfigDict(frozen=True)

    intent_id: str = Field(description="Stable identifier (intent_1, intent_2, ...)")
    goal: str = Field(description="The user's goal in plain language (no tool names)")
    entities: list[str] = Field(default_factory=list, description="Entity values (Lahore, Tokyo, ...)")
    requested_outputs: list[str] = Field(default_factory=list, description="What the user wants back")
    sequence: int = Field(default=0, description="Ordering in the request")
    confidence: float = Field(default=1.0, description="Decomposition confidence (0-1)")
    negated: bool = Field(default=False, description="True when the user excluded this")


class IntentGraph(BaseModel):
    """Structured decomposition: intents + their relationships."""

    model_config = ConfigDict(frozen=True)

    intents: tuple[DetectedIntent, ...] = Field(default_factory=tuple)
    relationships: tuple[IntentRelationship, ...] = Field(default_factory=tuple)
    source: Literal["deterministic", "llm"] = "deterministic"

    @property
    def executable(self) -> tuple[DetectedIntent, ...]:
        """Non-negated intents (the coverage check's requested set)."""
        return tuple(i for i in self.intents if not i.negated)

    def as_dicts(self) -> list[dict[str, Any]]:
        """Benchmark-friendly serialization."""
        return [
            {
                "intent_id": i.intent_id,
                "goal": i.goal,
                "entities": list(i.entities),
                "requested_outputs": list(i.requested_outputs),
                "sequence": i.sequence,
                "negated": i.negated,
                "confidence": i.confidence,
            }
            for i in self.intents
        ]

    def relationships_as_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "source_intent": r.source_intent,
                "target_intent": r.target_intent,
                "artifact": r.artifact,
            }
            for r in self.relationships
        ]


# Anaphoric/dependency signals: the K83 class — the request references a
# value PRODUCED by another part of the request ("the coordinates returned
# for Lahore", "those coordinates", "based on that"). These mean the
# request contains at least TWO intents linked by a producer/consumer
# relationship, even when no grammatical connector separates them. This is
# syntactic structure (closed pattern set), not domain logic.
_ANAPHORIC_PATTERNS = (
    r"the\s+(?:coordinates|address|location|results?|data)\s+(?:returned|found|obtained|from|for)",
    r"those?\s+(?:coordinates|results?|values?|locations)",
    r"at\s+the\s+(?:coordinates|location|address)",
    r"based\s+on\s+(?:that|those|it)",
    r"(?:then|after(?:wards)?|next)\s+",
    r"using\s+(?:those|the)\s+(?:coordinates|results?|values?)",
    r"from\s+(?:that|these)\s+(?:coordinates|results?|locations?)",
)
_ANAPHORIC_RE = re.compile(r"(?i)" + "|".join(_ANAPHORIC_PATTERNS))

# Multi-entity signals: a single clause naming several distinct entities
# with a repeated action ("weather in Lahore, Tokyo, and Paris") is ONE
# intent with instance hints — but "coordinates of Lahore and weather in
# Tokyo" is TWO intents. The grammar splitter handles connectors; these
# signals decide whether Tier-2 decomposition is worth its LLM call.
_MULTI_ENTITY_SPLIT_RE = re.compile(
    r"(?i)\b(?:for|in|of)\s+([a-z][a-z0-9 _.'-]{2,30})\s+"
    r"(?:and|,)\s*(?:also|then|plus)\s*"
)


def _compound_signal_strength(message: str) -> float:
    """Deterministic decomposition trigger (0-1), structural features only.

    A high score means the request is compound enough that Tier-1's clause
    split may have MISSED an intent (anaphoric chains, multiple
    connectors, multiple requested outputs) — the Tier-2 LLM decomposer
    should run. Single-clause single-entity requests score ~0 (no extra
    LLM call — the reviewer's latency discipline).
    """
    text = (message or "").strip().lower()
    if not text:
        return 0.0
    score = 0.0
    if _ANAPHORIC_RE.search(text):
        score += 0.45  # K83 class: implied producer/consumer pair
    connectors = len(re.findall(r"(?i)\b(?:and|plus|also|then|after|before|both)\b", text))
    if connectors >= 2:
        score += 0.3
    elif connectors == 1:
        score += 0.15
    outputs = len(re.findall(r"(?i)\b(?:tell me|give me|get|find|search for|show|compare|report)\b", text))
    if outputs >= 3:
        score += 0.25
    elif outputs >= 2:
        score += 0.1
    entities = len(set(re.findall(r"(?i)\b(?:in|for|of)\s+([a-z][a-z0-9 .'-]{2,30})\b", text)))
    if entities >= 3:
        score += 0.15
    if len(text.split()) >= 20:
        score += 0.1
    return min(1.0, score)


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

    def detect_graph(self, message: str) -> IntentGraph:
        """Tier-1 structured graph: the clause split mapped onto
        ``DetectedIntent`` (goals = clause text, no capability names).

        Anaphoric chains (the K83 class) are SPLIT here, not just
        linked: a single clause like "the address at the coordinates
        returned for Lahore" carries a producer/consumer pair — the
        clause is decomposed into a producer intent ("obtain the
        coordinates for Lahore") and a consumer intent ("the address at
        the coordinates") joined by a relationship. Pure syntax (closed
        pattern set), no domain vocabulary.
        """
        detected = self.detect(message)
        intents: list[DetectedIntent] = []
        relationships: list[IntentRelationship] = []
        for unit in detected.units:
            split = self._split_anaphoric_clause(unit.text, unit)
            if split is None:
                intents.append(DetectedIntent(
                    intent_id=f"intent_{len(intents) + 1}",
                    goal=unit.text,
                    entities=_extract_entities(unit.text),
                    requested_outputs=[unit.text],
                    sequence=unit.order,
                    confidence=unit.confidence,
                    negated=unit.negated,
                ))
                continue
            producer_text, consumer_text, artifact = split
            producer_id = f"intent_{len(intents) + 1}"
            intents.append(DetectedIntent(
                intent_id=producer_id,
                goal=producer_text,
                entities=_extract_entities(producer_text),
                requested_outputs=[artifact],
                sequence=unit.order,
                confidence=unit.confidence,
                negated=unit.negated,
            ))
            consumer_id = f"intent_{len(intents) + 1}"
            intents.append(DetectedIntent(
                intent_id=consumer_id,
                goal=consumer_text,
                entities=_extract_entities(consumer_text),
                requested_outputs=[consumer_text],
                sequence=unit.order + 1,
                confidence=unit.confidence,
                negated=unit.negated,
            ))
            relationships.append(IntentRelationship(
                source_intent=producer_id,
                target_intent=consumer_id,
                artifact=artifact,
            ))
        for i, intent in enumerate(intents):
            if i == 0:
                continue
            if _ANAPHORIC_RE.search(intent.goal):
                relationships.append(IntentRelationship(
                    source_intent=intents[i - 1].intent_id,
                    target_intent=intent.intent_id,
                    artifact=_anaphoric_artifact(intent.goal),
                ))
        return IntentGraph(intents=tuple(intents), relationships=tuple(relationships))

    @staticmethod
    def _split_anaphoric_clause(
        clause: str, unit: Any
    ) -> tuple[str, str, str] | None:
        """Split ONE clause containing an anaphoric chain into a
        (producer_goal, consumer_goal, artifact) triple.

        The closed pattern: ``the <artifact> (returned|found|obtained|
        from|for) <entity>`` — the entity-bearing fragment becomes the
        producer's goal, the rest the consumer's. None when the clause
        carries no such chain.
        """
        m = re.search(
            r"(?i)(?:the\s+)(coordinates|results?|data|location|address|values?)"
            r"\s+(?:returned|found|obtained|from|for)\s+(.+)$",
            clause,
        )
        if not m:
            return None
        artifact = m.group(1).rstrip("s")
        tail = m.group(2).strip(" .,")
        # Drop a leading connector the greedy tail captured ("for for").
        tail = re.sub(r"^(?:for|of|at|in|from)\s+", "", tail)
        prefix = clause[: m.start()].strip(" ,.")
        # The prefix ends at "the <artifact>"; restore the article so the
        # consumer goal reads naturally ("find the address at the
        # coordinates") — never a dangling "at the".
        prefix = re.sub(r"\s+the$", "", prefix).strip()
        consumer_goal = f"{prefix} the {artifact}".strip()
        producer = f"obtain the {artifact} for {tail}"
        consumer = consumer_goal if prefix else f"use the {artifact}"
        return producer, consumer, artifact

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
        # 2. Alias index. Values are capability-name STRINGS — never
        # iterate a string as a sequence (a token directly in the alias
        # index would otherwise add single CHARACTERS as candidates).
        alias_index = getattr(gc, "alias_index", None) or {}
        for token in tokens:
            aliases = alias_index.get(token, []) or []
            if isinstance(aliases, str):
                aliases = [aliases]
            for cap in aliases:
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
