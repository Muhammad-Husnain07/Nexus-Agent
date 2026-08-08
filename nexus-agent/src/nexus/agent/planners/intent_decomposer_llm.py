"""IntentDecomposerLLM — the Tier-2 intent decomposition fallback (P4-4).

Invoked ONLY when the deterministic Tier-1 detector's confidence is low
or a bounded repair cycle failed on intent-coverage violations. One
focused LLM call emitting the intent units — the planner then maps each
unit to capabilities (its own job). Cached by query fingerprint so a
repeated failing request does not re-pay the call.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from nexus.agent.planners.intent_detector import (
    DetectedIntents,
    IntentUnit,
)

logger = structlog.get_logger("nexus.agent.planners.intent_decomposer")

_DECOMPOSER_PROMPT = """You are an intent decomposer. Split the user's request into its
independent executable units. One unit per distinct thing the user asks for.

Rules:
- A unit is a clause the user wants executed ("weather in Lahore").
- NEVER include capability or tool names — plain request language only.
- "don't/not/never" → mark that unit negated=true (the user excluded it).
- Comparisons ("compare X and Y") → one unit with instance_hint=2.
- Lists ("posts 1 and 5") → one unit with instance_hint=2.
- Greetings/pleasantries are NOT units (skip them).
- If the request is pure conversation (no executable request), emit an
  empty units list.

Return ONLY JSON: {{"units": [{{"text": str, "negated": bool, "instance_hint": int}}]}}"""


async def decompose_with_llm(llm: Any, model: str, message: str,
                             cache: Any = None) -> DetectedIntents | None:
    """Tier-2 decomposition. Returns None on any failure (the caller
    falls back to the Tier-1 result — the rare path must never break the
    common path)."""
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
            max_tokens=600,
        )
        payload = json.loads((response.content or "") or "{}")
        units = [
            IntentUnit(
                text=str(u.get("text", "")).strip(),
                negated=bool(u.get("negated", False)),
                instance_hint=max(1, int(u.get("instance_hint", 1) or 1)),
                order=order,
            )
            for order, u in enumerate(payload.get("units", []))
            if str(u.get("text", "")).strip()
        ]
        result = DetectedIntents(
            units=tuple(units), confidence=1.0, source="llm",
        )
        if cache is not None:
            try:
                cache.set(query_fp, result)
            except Exception:
                pass
        return result
    except Exception as exc:
        logger.warning("intent_decomposer.failed", error=str(exc)[:150])
        return None
