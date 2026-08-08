"""MediaRenderer — readable rendering of entertainment/media artifacts
(anime, manga, film listings) from their declared flat fields.
"""

from __future__ import annotations

from nexus.artifacts.renderers.base import ArtifactRenderer
from nexus.artifacts.renderers.registry import RendererRegistry


class MediaRenderer(ArtifactRenderer):
    """Render anime/manga/film artifacts: title, format, volume, score."""

    def render(self, data: dict) -> str:
        if not data:
            return ""
        title = data.get("title")
        if not title:
            return ""
        parts: list[str] = [str(title)]
        fmt = data.get("format")
        if fmt:
            parts.append(f"[{fmt}]")
        for volume_key in ("chapters", "episodes"):
            if data.get(volume_key) is not None:
                parts.append(f"{volume_key}: {data[volume_key]}")
        score = data.get("average_score")
        if score is not None:
            parts.append(f"score {score}/100")
        return " ".join(parts)


def _register() -> None:
    renderer = MediaRenderer()
    RendererRegistry.register("search_anime", renderer)
    RendererRegistry.register("search_manga", renderer)
    RendererRegistry.register("get_ghibli_films", renderer)


_register()
