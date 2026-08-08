"""BooksRenderer — readable rendering of book-search artifacts."""

from __future__ import annotations

from nexus.artifacts.renderers.base import ArtifactRenderer
from nexus.artifacts.renderers.registry import RendererRegistry


class BooksRenderer(ArtifactRenderer):
    """Render a book-search artifact (title, authors, result count)."""

    def render(self, data: dict) -> str:
        if not data:
            return ""
        title = data.get("title")
        authors = data.get("authors")
        count = data.get("books_count")
        if not title and not authors:
            return ""
        parts: list[str] = []
        if title:
            parts.append(str(title))
        if authors:
            if isinstance(authors, list):
                authors_text = ", ".join(str(a) for a in authors)
            else:
                authors_text = str(authors)
            parts.append(f"by {authors_text}")
        if count is not None:
            parts.append(f"({count} results found)")
        return " ".join(parts)


def _register() -> None:
    RendererRegistry.register("search_books", BooksRenderer())


_register()
