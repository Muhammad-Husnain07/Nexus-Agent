"""Typed renderer regression tests — every registered domain renderer must
produce readable natural text from its declared flat fields (never raw
JSON, never empty when the data is present).
"""

from __future__ import annotations

from nexus.artifacts.renderers.registry import RendererRegistry


def _setup() -> None:
    RendererRegistry.initialize()


def test_weather_renderer_natural_text():
    _setup()
    text = RendererRegistry.get("get_current_weather").render({
        "temperature_c": 29.5, "windspeed_kmh": 8.0, "weathercode": 0,
        "recorded_at": "2026-08-07T08:00", "is_day": 1,
    })
    assert "29.5°C" in text
    assert "clear sky" in text
    assert text.endswith(".")


def test_exchange_renderer_any_currency():
    _setup()
    text = RendererRegistry.get("get_exchange_rates").render({
        "base_code": "USD", "eur_rate": 0.92, "pkr_rate": 278.4,
        "updated": "2026-08-07",
    })
    assert "EUR" in text
    assert "PKR" in text
    assert "0.92" in text


def test_media_renderer():
    _setup()
    text = RendererRegistry.get("search_anime").render({
        "title": "One Piece", "format": "TV", "episodes": 12,
        "average_score": 78,
    })
    assert "One Piece" in text
    assert "78/100" in text


def test_country_and_books_renderers():
    _setup()
    country = RendererRegistry.get("get_country_info").render({
        "country": "Pakistan", "description": "A country in South Asia",
        "page_url": "https://example.com",
    })
    assert "Pakistan" in country
    assert "https://example.com" in country
    books = RendererRegistry.get("search_books").render({
        "title": "Dune", "authors": ["Frank Herbert"], "books_count": 1,
    })
    assert "Dune" in books
    assert "Frank Herbert" in books


def test_registry_get_alias_exists():
    """The response renderer path calls ``RendererRegistry.get`` — it must
    resolve (a missing method silently degrades everything to JSON)."""
    _setup()
    assert RendererRegistry.get("get_current_weather") is RendererRegistry.get_renderer(
        "get_current_weather"
    )


def test_unknown_tool_falls_back_to_generic():
    _setup()
    text = RendererRegistry.get("no_such_tool").render({"alpha": 7})
    assert "7" in text
