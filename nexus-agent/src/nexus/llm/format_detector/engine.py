"""Format detection engine — probes a model and deduces its expected prompt format.

Sends a tiny probe message, analyzes the response via fingerprint matching,
and returns the detected format name. Results are cached per model string.
"""

from __future__ import annotations

import structlog

from nexus.llm.format_detector.fingerprints import FINGERPRINTS

log = structlog.get_logger(__name__)

_probe_cache: dict[str, str] = {}


def score_format(response_text: str) -> dict[str, float]:
    """Score every known format against the probe response text.

    Higher score = better match. Scores are normalized 0.0-1.0.
    Returns dict of {format_name: score}.
    """
    scores: dict[str, float] = {}
    for fmt_name, fp in FINGERPRINTS.items():
        score = 0.0
        echo_count = len(fp.echo_patterns) or 1
        for pat in fp.echo_patterns:
            if pat.search(response_text):
                score += 1.0 / echo_count
        for pat in fp.exclude_patterns:
            if pat.search(response_text):
                score -= 0.5
        scores[fmt_name] = max(0.0, score * fp.weight)

    if not scores:
        return {"raw": 1.0}

    max_score = max(scores.values())
    if max_score > 0:
        scores = {k: v / max_score for k, v in scores.items()}
    return scores


def detect_format_sync(response_text: str) -> str:
    """Detect format from a probe response synchronously."""
    scores = score_format(response_text)
    best = max(scores, key=lambda k: scores[k])
    best_score = scores[best]

    log.info("format_detection.result", best=best, score=best_score, all_scores=str(scores))

    if best_score < 0.3:
        return "raw"
    return best


def cached_detect_format(model: str) -> str | None:
    """Return cached format for a model, or None."""
    return _probe_cache.get(model)


def set_cached_format(model: str, fmt: str) -> None:
    """Cache the detected format for a model."""
    _probe_cache[model] = fmt
