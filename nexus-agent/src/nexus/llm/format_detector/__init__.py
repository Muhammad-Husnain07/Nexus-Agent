"""Dynamic prompt format detection — no hardcoded model names.

Detects what prompt format an LLM expects by sending a tiny probe
message and analyzing the response with regex-based fingerprints.
"""
from nexus.llm.format_detector.engine import score_format, cached_detect_format, set_cached_format, detect_format_sync
from nexus.llm.format_detector.fallback import FORMAT_HINTS, get_fallback_format
from nexus.llm.format_detector.fingerprints import FINGERPRINTS, FormatFingerprint

__all__ = [
    "FINGERPRINTS", "FormatFingerprint", "cached_detect_format",
    "detect_format_sync", "get_fallback_format", "score_format", "FORMAT_HINTS",
    "set_cached_format",
]
