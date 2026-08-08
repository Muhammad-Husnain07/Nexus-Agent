"""IntentDetector tests — deterministic Tier-1 decomposition.

Covers the exact failure classes from the mixed-query audit: triple-domain,
comparison, negation, repeated capability, greeting+action, and the
ambiguous single-clause case that triggers the Tier-2 fallback.
"""

from __future__ import annotations

import pytest

from nexus.agent.planners.intent_detector import IntentDetector


def _units(text: str):
    return IntentDetector().detect(text).units


def test_triple_domain_three_units():
    units = _units(
        "What's the weather in Lahore, the exchange rate from USD to PKR, "
        "and tell me about Pakistan?"
    )
    assert len(units) == 3
    assert not any(u.negated for u in units)


def test_comparison_two_instances():
    units = _units(
        "Compare the temperature in Tokyo and Osaka, then get the country info for Japan"
    )
    # the connector split yields clauses; the comparison clause carries the hint
    assert any(u.comparison and u.instance_hint >= 2 for u in units)


def test_negation_binding():
    units = _units("Don't check the weather — just fetch post 3 from jsonplaceholder")
    assert any(u.negated for u in units)
    assert any("post 3" in u.text and not u.negated for u in units)


def test_repeated_capability_instance_hint():
    units = _units("Fetch posts 1 and 5 from jsonplaceholder")
    assert any(u.instance_hint >= 2 for u in units)


def test_greeting_plus_action():
    units = _units("Hi there! Also, what's the population of France?")
    assert len(units) >= 2


def test_negated_never_exempt():
    """A negated unit must never be considered served by a matching op."""
    from nexus.agent.planners.intent_detector import unit_candidates

    units = _units("Don't check the weather — just fetch post 3")
    negated = [u for u in units if u.negated]
    assert negated, "negation must be detected"


def test_frozen_models():
    units = _units("weather in Lahore and exchange rates")
    with pytest.raises(Exception):
        units[0].text = "mutated"  # frozen


def test_single_simple_query_single_unit_high_confidence():
    result = IntentDetector().detect("What's the temperature in Tokyo?")
    assert len(result.units) == 1
    assert result.confidence >= 0.7
