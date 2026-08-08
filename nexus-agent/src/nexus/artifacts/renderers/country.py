"""CountryRenderer — readable rendering of country-information artifacts."""

from __future__ import annotations

from nexus.artifacts.renderers.base import ArtifactRenderer
from nexus.artifacts.renderers.registry import RendererRegistry


class CountryRenderer(ArtifactRenderer):
    """Render a country artifact (name, description, reference URL)."""

    def render(self, data: dict) -> str:
        if not data:
            return ""
        country = data.get("country") or data.get("title")
        description = data.get("description") or data.get("extract")
        url = data.get("page_url")
        if not country and not description:
            return ""
        if country and description:
            text = f"{country}: {description}"
        else:
            text = country or description or ""
        if url:
            text = f"{text} ({url})"
        return text


def _register() -> None:
    RendererRegistry.register("get_country_info", CountryRenderer())


_register()
