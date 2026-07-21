"""Content Studio — demo FastAPI app that Nexus Agent can orchestrate.

Run with:
    python examples/demo_app/main.py

The app serves on http://localhost:8080 with OpenAPI at /docs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from examples.demo_app.models import Article, ArticleCreate, ArticleUpdate, seed_data

# ── App init ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Content Studio API",
    description="A simple content management system for demo purposes. "
    "Nexus Agent orchestrates these endpoints as registered tools.",
    version="1.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── In-memory store ──────────────────────────────────────────────────────────

_store = seed_data()


def _get_article(article_id: str) -> Article:
    for a in _store["articles"]:
        if a.id == article_id:
            return a
    raise HTTPException(status_code=404, detail="Article not found")


# ── Routes ───────────────────────────────────────────────────────────────────


@app.get("/articles")
async def list_articles(category: str | None = None, status: str | None = None, tag: str | None = None):
    """List articles with optional filters."""
    results = _store["articles"]
    if category:
        results = [a for a in results if a.category == category]
    if status:
        results = [a for a in results if a.status == status]
    if tag:
        results = [a for a in results if tag in (a.tags or [])]
    articles = [
        {
            "id": a.id,
            "title": a.title,
            "content": a.content,
            "category": a.category,
            "tags": a.tags,
            "status": a.status,
            "created_at": a.created_at,
            "updated_at": a.updated_at,
        }
        for a in results
    ]
    return {"articles": articles, "total": len(articles)}


@app.get("/articles/{article_id}")
async def get_article(article_id: str):
    article = _get_article(article_id)
    return {
        "id": article.id,
        "title": article.title,
        "content": article.content,
        "category": article.category,
        "tags": article.tags,
        "status": article.status,
        "created_at": article.created_at.isoformat(),
        "updated_at": article.updated_at.isoformat(),
    }


@app.post("/articles")
async def create_article(data: ArticleCreate):
    article = Article(
        id=f"a{str(uuid.uuid4())[:7]}",
        title=data.title,
        content=data.content,
        category=data.category or "General",
        tags=data.tags or [],
        status="draft",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    _store["articles"].append(article)
    return {"id": article.id, "status": "draft"}


@app.put("/articles/{article_id}")
async def update_article(article_id: str, data: ArticleUpdate):
    article = _get_article(article_id)
    if data.title is not None:
        article.title = data.title
    if data.content is not None:
        article.content = data.content
    if data.category is not None:
        article.category = data.category
    if data.tags is not None:
        article.tags = data.tags
    article.updated_at = datetime.now(UTC)
    return {"id": article.id, "status": "updated"}


@app.post("/articles/{article_id}/publish")
async def publish_article(article_id: str):
    article = _get_article(article_id)
    article.status = "published"
    article.updated_at = datetime.now(UTC)
    return {"id": article.id, "status": "published"}


@app.delete("/articles/{article_id}")
async def delete_article(article_id: str):
    article = _get_article(article_id)
    _store["articles"] = [a for a in _store["articles"] if a.id != article_id]
    return {"id": article.id, "status": "deleted"}


@app.post("/articles/{article_id}/preview")
async def preview_article(article_id: str):
    article = _get_article(article_id)
    html = f"""<html><body><h1>{article.title}</h1><p>{article.content}</p></body></html>"""
    return {"html": html, "id": article.id}


@app.get("/categories")
async def list_categories():
    return {"categories": [{"id": 1, "name": "Tech"}, {"id": 2, "name": "Science"}, {"id": 3, "name": "Sports"}, {"id": 4, "name": "News"}]}


@app.get("/tags")
async def list_tags():
    return {"tags": [{"id": 1, "name": "AI"}, {"id": 2, "name": "ML"}, {"id": 3, "name": "Cloud"}, {"id": 4, "name": "SaaS"}, {"id": 5, "name": "Research"}], "total": 5}


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8081)
