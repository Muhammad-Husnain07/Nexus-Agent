"""IntentDecomposerLLM — the Tier-2 STRUCTURED intent decomposition (P0-C).

Invoked ONLY when the adaptive compound-signal trigger fires (anaphoric
chains, multiple connectors/outputs — the K83 class). ONE focused LLM call
emitting the STRUCTURED intent graph — goals (never tool names), entities,
requested outputs, and relationships (a later intent consuming an earlier
one's output). The resolver then maps each goal to capabilities — this
layer discovers WHAT, resolution decides HOW.

Cached by query fingerprint so a repeated failing request does not re-pay
the call. Graceful-fail: any failure returns None and the caller falls
back to the deterministic Tier-1 graph.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from nexus.agent.planners.intent_detector import (
    DetectedIntent,
    IntentGraph,
    IntentRelationship,
)

logger = structlog.get_logger("nexus.agent.planners.intent_decomposer")


def _parse_json_salvage(content: str) -> dict[str, Any] | None:
    """Robust JSON parse: strip fences, salvage the first balanced JSON
    object from a chatty response (the nano model's trailing-text class),
    and reject outright garbage."""
    text = str(content or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n```$", "", text)
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return None
    return None

_DECOMPOSER_PROMPT = """You decompose a user request into its independent executable intents.

For each intent emit:
- "goal": what the user wants in plain request language — NEVER tool or capability names
- "entities": the concrete values the intent operates on ("Lahore", "facebook/react")
- "requested_outputs": what the user wants back ("coordinates", "address", "weather")
- "sequence": the order in the request (0-based)
- "negated": true only when the user explicitly excluded this (don't/not/never)

RELATIONSHIPS (critical):
When one intent CONSUMES a value produced by another intent — anaphoric
references like "the address at the coordinates returned for Lahore",
"reverse geocode THOSE coordinates", "using the results from the previous
step", "then", "after that" — emit a relationship entry:
  "relationships": [{"source_intent": "intent_1", "target_intent": "intent_2", "artifact": "coordinates"}]

Examples:
"Get the coordinates of Lahore and reverse geocode those coordinates" →
  intents: [
    {"intent_id": "intent_1", "goal": "obtain the coordinates of Lahore", "entities": ["Lahore"], "requested_outputs": ["coordinates"], "sequence": 0, "negated": false},
    {"intent_id": "intent_2", "goal": "reverse geocode the coordinates", "entities": [], "requested_outputs": ["address"], "sequence": 1, "negated": false}
  ],
  relationships: [{"source_intent": "intent_1", "target_intent": "intent_2", "artifact": "coordinates"}]

Rules:
- Comparisons ("compare X and Y") and lists ("posts 1 and 5") are ONE intent (do not split).
- Multiple distinct actions are SEPARATE intents.
- Greetings/pleasantries are NOT intents.
- Pure conversation (no executable request) → empty intents.
- NEVER invent capabilities, APIs, or tools.

Return ONLY JSON: {"intents": [...], "relationships": [...]}"""


async def decompose_with_llm(llm: Any, model: str, message: str,
                             cache: Any = None) -> IntentGraph | None:
    """Tier-2 structured decomposition. Returns None on any failure (the
    caller falls back to the Tier-1 graph — the rare path must never break
    the common path)."""
    query_fp = message.strip().lower()
    if cache is not None:
        try:
            hit = cache.get(query_fp)
            if hit is not None:
                return hit
        except Exception:
            pass
    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": _DECOMPOSER_PROMPT},
                {"role": "user", "content": message},
            ],
            temperature=0.0,
            max_tokens=900,
            response_format={"type": "json_object"},
        )
        content = (response.content or "") if hasattr(response, "content") else ""
        if response.failed if hasattr(response, "failed") else False:
            logger.warning("intent_decomposer.llm_failed", error=str(response.error)[:150])
            return None
        payload = _parse_json_salvage(content)
        if payload is None:
            return None
        intents: list[DetectedIntent] = []
        for order, raw in enumerate(payload.get("intents", []) or []):
            if not isinstance(raw, dict):
                continue
            goal = str(raw.get("goal") or "").strip()
            if not goal:
                continue
            intents.append(DetectedIntent(
                intent_id=str(raw.get("intent_id") or f"intent_{order + 1}"),
                goal=goal,
                entities=[str(e) for e in (raw.get("entities") or []) if str(e).strip()],
                requested_outputs=[str(o) for o in (raw.get("requested_outputs") or []) if str(o).strip()],
                sequence=int(raw.get("sequence", order) or order),
                negated=bool(raw.get("negated", False)),
            ))
        relationships: list[IntentRelationship] = []
        ids = {i.intent_id for i in intents}
        for raw in payload.get("relationships", []) or []:
            if not isinstance(raw, dict):
                continue
            src = str(raw.get("source_intent") or "")
            tgt = str(raw.get("target_intent") or "")
            if src in ids and tgt in ids:
                relationships.append(IntentRelationship(
                    source_intent=src,
                    target_intent=tgt,
                    artifact=str(raw.get("artifact") or "output"),
                ))
        result = IntentGraph(intents=tuple(intents), relationships=tuple(relationships), source="llm")
        if cache is not None:
            try:
                cache.set(query_fp, result)
            except Exception:
                pass
        return result
    except Exception as exc:
        logger.warning("intent_decomposer.failed", error=str(exc)[:150])
        return None
