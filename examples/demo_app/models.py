"""In-memory data models for the Content Studio demo app."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class Article(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str
    content: str
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    status: str = "draft"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ArticleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200, examples=["AI Trends in 2026"])
    content: str = Field(min_length=1, examples=["Artificial intelligence is ..."])
    category: str = Field(default="general", examples=["Tech"])
    tags: list[str] = Field(default_factory=list, examples=[["AI", "ML"]])


class ArticleUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    category: str | None = None
    tags: list[str] | None = None


# ── In-memory data store ──────────────────────────────────────────────


def seed_data() -> dict[str, list[Article]]:
    return {
        "articles": [
            Article(
                id="a0000001",
                title="AI Breakthroughs in 2026",
                content="This year saw remarkable advances in large language models...",
                category="Tech",
                tags=["AI", "ML"],
                status="published",
                created_at="2026-07-01T08:00:00Z",
                updated_at="2026-07-01T08:00:00Z",
            ),
            Article(
                id="a0000002",
                title="Cloud Migration Strategies",
                content="Moving to the cloud requires careful planning...",
                category="Tech",
                tags=["Cloud", "SaaS"],
                status="published",
                created_at="2026-07-02T10:00:00Z",
                updated_at="2026-07-02T10:00:00Z",
            ),
            Article(
                id="a0000003",
                title="The Future of Quantum Computing",
                content="Quantum computing is poised to revolutionise...",
                category="Science",
                tags=["Research"],
                status="draft",
                created_at="2026-07-10T14:00:00Z",
                updated_at="2026-07-10T14:00:00Z",
            ),
        ],
        "categories": [
            {"id": 1, "name": "Tech", "slug": "tech"},
            {"id": 2, "name": "Business", "slug": "business"},
            {"id": 3, "name": "Science", "slug": "science"},
        ],
        "tags": [
            {"id": 1, "name": "AI"},
            {"id": 2, "name": "ML"},
            {"id": 3, "name": "Cloud"},
            {"id": 4, "name": "SaaS"},
            {"id": 5, "name": "Research"},
        ],
    }
