"""NormalizationRegistry — pluggable entity normalizers.

Normalizers are registered by field name patterns. At normalization time,
each entity field is checked against all registered normalizer patterns.
Matching normalizers transform the value inline.

No hardcoded field names — normalizers declare which fields they handle
via pattern functions or tag-based matching.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import structlog

logger = structlog.get_logger("nexus.agent.registry.normalization")

# A normalizer is a callable that takes (field_name: str, value: Any) and
# returns (normalized_value: Any, applied: bool).  If ``applied`` is False
# the original value is kept.
NormalizerFn = Callable[[str, Any], tuple[Any, bool]]


# ============================================================================
# Built-in normalizers (pluggable, not hardcoded by field name)
# ============================================================================


def _normalize_date(field: str, value: Any) -> tuple[Any, bool]:
    """Resolve relative date references (today, tomorrow) to ISO dates.

    Applies to any field whose name contains 'date', 'day', 'time',
    'deadline', 'schedule', or 'when'.
    """
    if not isinstance(value, str):
        return value, False
    date_keywords = {"date", "day", "time", "deadline", "schedule", "when", "at"}
    if not any(kw in field.lower() for kw in date_keywords):
        return value, False

    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    v = value.strip().lower()

    if v in ("today", "now", "present"):
        return today.isoformat(), True
    if v == "tomorrow":
        return (today + timedelta(days=1)).isoformat(), True
    if v == "yesterday":
        return (today - timedelta(days=1)).isoformat(), True
    if v in ("next week", "next_week"):
        return (today + timedelta(weeks=1)).isoformat(), True
    if v in ("next month", "next_month"):
        return (today + timedelta(days=30)).isoformat(), True
    if v in ("next year", "next_year"):
        return (today + timedelta(days=365)).isoformat(), True

    # Check for "in X days/weeks" pattern
    m = re.match(r"in\s+(\d+)\s*(day|days|week|weeks|month|months)", v)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        if unit in ("day", "days"):
            delta = timedelta(days=num)
        elif unit in ("week", "weeks"):
            delta = timedelta(weeks=num)
        else:
            delta = timedelta(days=num * 30)
        return (today + delta).isoformat(), True

    return value, False


def _normalize_location(field: str, value: Any) -> tuple[Any, bool]:
    """Expand common location abbreviations.

    Applies to any field whose name contains 'city', 'location',
    'place', 'address', 'country', 'region', or 'state'.
    """
    if not isinstance(value, str):
        return value, False
    loc_keywords = {"city", "location", "place", "address", "country", "region", "state", "town"}
    if not any(kw in field.lower() for kw in loc_keywords):
        return value, False

    abbreviations = {
        "nyc": "New York City",
        "la": "Los Angeles",
        "sf": "San Francisco",
        "chi": "Chicago",
        "philly": "Philadelphia",
        "dc": "Washington D.C.",
        "london": "London",
        "paris": "Paris",
        "tokyo": "Tokyo",
        "berlin": "Berlin",
        "sydney": "Sydney",
        "dubai": "Dubai",
        "sg": "Singapore",
        "hk": "Hong Kong",
    }

    v = value.strip()
    v_lower = v.lower()
    if v_lower in abbreviations:
        return abbreviations[v_lower], True

    return value, False


def _normalize_currency(field: str, value: Any) -> tuple[Any, bool]:
    """Normalize currency codes and symbols to uppercase ISO codes.

    Applies to any field whose name contains 'currency', 'price',
    'cost', 'budget', 'amount', 'fee', or 'money'.
    """
    if not isinstance(value, str):
        return value, False
    currency_keywords = {"currency", "price", "cost", "budget", "amount", "fee", "money", "salary", "rate"}
    if not any(kw in field.lower() for kw in currency_keywords):
        return value, False

    currency_map = {
        "usd": "USD", "$": "USD", "dollar": "USD", "dollars": "USD",
        "eur": "EUR", "€": "EUR", "euro": "EUR", "euros": "EUR",
        "gbp": "GBP", "£": "GBP", "pound": "GBP", "pounds": "GBP",
        "jpy": "JPY", "¥": "JPY", "yen": "JPY",
        "cny": "CNY", "yuan": "CNY",
        "inr": "INR", "₹": "INR", "rupee": "INR", "rupees": "INR",
        "aed": "AED", "dirham": "AED", "dhs": "AED",
        "sar": "SAR", "riyal": "SAR",
        "pkr": "PKR", "rupee": "PKR", "rupees": "PKR",
    }

    v = value.strip().lower()
    if v in currency_map:
        return currency_map[v], True

    # Uppercase known ISO codes
    if v.upper() in ("USD", "EUR", "GBP", "JPY", "CNY", "INR", "AED", "SAR", "PKR", "CHF", "AUD", "CAD", "NZD"):
        return v.upper(), True

    return value, False


def _normalize_text(field: str, value: Any) -> tuple[Any, bool]:
    """Apply lightweight text normalization.

    Applies to any string value: strips whitespace, normalizes spaces.
    """
    if not isinstance(value, str):
        return value, False
    normalized = " ".join(value.strip().split())
    if normalized != value:
        return normalized, True
    return value, False


# ============================================================================
# Built-in normalizers registry
# ============================================================================

_BUILTIN_NORMALIZERS: list[NormalizerFn] = [
    _normalize_text,
    _normalize_date,
    _normalize_location,
    _normalize_currency,
]


class NormalizationRegistry:
    """Pluggable registry for entity value normalizers.

    Normalizers are matched to fields by keyword pattern — no hardcoded
    field names. Register custom normalizers via ``register()``.
    """

    def __init__(self) -> None:
        self._normalizers: list[NormalizerFn] = list(_BUILTIN_NORMALIZERS)

    def register(self, normalizer: NormalizerFn) -> None:
        """Register a normalizer function.

        The function receives (field_name, value) and returns
        (normalized_value, applied).  If applied is False, the
        original value is preserved.
        """
        self._normalizers.append(normalizer)

    def normalize(self, field: str, value: Any) -> Any:
        """Run all normalizers on a single field+value pair.

        Returns the normalized value (or original if no normalizer matched).
        """
        for normalizer in self._normalizers:
            result, applied = normalizer(field, value)
            if applied:
                return result
        return value

    def normalize_entities(self, entities: dict[str, Any]) -> dict[str, Any]:
        """Normalize all entity values in a dict.

        Returns a new dict with normalized values. Non-matching fields
        are returned unchanged.
        """
        return {k: self.normalize(k, v) for k, v in entities.items()}


_singleton_registry: NormalizationRegistry | None = None


def get_normalization_registry() -> NormalizationRegistry:
    """Get the singleton NormalizationRegistry instance."""
    global _singleton_registry
    if _singleton_registry is None:
        _singleton_registry = NormalizationRegistry()
    return _singleton_registry
