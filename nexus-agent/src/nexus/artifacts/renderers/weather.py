"""WeatherRenderer — natural-language rendering of current-weather artifacts.

Presentation only (no agent logic): reads the tool's declared flat fields
(``x-artifact-fields``) and formats them. The WMO weather-code condition
mapping is a declarative presentation table; anything missing degrades to
the GenericRenderer fallback.
"""

from __future__ import annotations

from nexus.artifacts.renderers.base import ArtifactRenderer
from nexus.artifacts.renderers.registry import RendererRegistry

# WMO weather-code → short condition phrase (presentation table).
_WMO_CONDITIONS = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    61: "light rain",
    63: "moderate rain",
    65: "heavy rain",
    71: "light snow",
    73: "moderate snow",
    75: "heavy snow",
    80: "light showers",
    81: "moderate showers",
    82: "violent showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "severe thunderstorm with hail",
}


class WeatherRenderer(ArtifactRenderer):
    """Render a weather artifact as a readable one-line briefing."""

    def render(self, data: dict) -> str:
        if not data:
            return ""
        temp = data.get("temperature_c")
        wind = data.get("windspeed_kmh")
        code = data.get("weathercode")
        when = data.get("recorded_at")
        parts: list[str] = []
        if temp is not None:
            parts.append(f"{temp}°C")
        condition = _WMO_CONDITIONS.get(int(code)) if code is not None else None
        if condition:
            parts.append(condition)
        if wind is not None:
            parts.append(f"wind {wind} km/h")
        if when:
            parts.append(f"recorded {when}")
        if not parts:
            return ""
        return "Current weather: " + ", ".join(parts) + "."


def _register() -> None:
    RendererRegistry.register("get_current_weather", WeatherRenderer())


_register()
