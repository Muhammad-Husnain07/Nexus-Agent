"""Content Studio — demo FastAPI app that Nexus Agent can orchestrate.

Run with:
    python examples/demo_app/main.py

The app serves on http://localhost:8080 with OpenAPI at /docs.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import uvicorn
from fastapi import FastAPI, HTTPException, Request
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

# ── Auth stub ────────────────────────────────────────────────────────────────

AUTH_TOKEN = "demo-token"


async def _verify_auth(request: Request) -> None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized — use Bearer demo-token")


# ── In-memory store ──────────────────────────────────────────────────────────

_store = seed_data()


def _get_article(article_id: str) -> Article:
    for a in _store["articles"]:
        if a.id == article_id:
            return a
    raise HTTPException(status_code=404, detail="Article not found")


# ── Article endpoints ────────────────────────────────────────────────────────


@app.get("/articles", tags=["articles"])
async def list_articles(
    request: Request,
    category: str | None = None,
    status: str | None = None,
    tag: str | None = None,
) -> dict:
    await _verify_auth(request)
    results = _store["articles"]
    if category:
        results = [a for a in results if a.category.lower() == category.lower()]
    if status:
        results = [a for a in results if a.status.lower() == status.lower()]
    if tag:
        results = [a for a in results if tag.lower() in [t.lower() for t in a.tags]]
    return {"articles": [a.model_dump(mode="json") for a in results], "total": len(results)}


@app.post("/articles", status_code=201, tags=["articles"])
async def create_article(request: Request, body: ArticleCreate) -> dict:
    await _verify_auth(request)
    article = Article(
        title=body.title,
        content=body.content,
        category=body.category,
        tags=body.tags,
    )
    _store["articles"].append(article)
    return {"article": article.model_dump(mode="json")}


@app.get("/articles/{article_id}", tags=["articles"])
async def get_article(request: Request, article_id: str) -> dict:
    await _verify_auth(request)
    a = _get_article(article_id)
    return {"article": a.model_dump(mode="json")}


@app.put("/articles/{article_id}", tags=["articles"])
async def update_article(request: Request, article_id: str, body: ArticleUpdate) -> dict:
    await _verify_auth(request)
    a = _get_article(article_id)
    if body.title is not None:
        a.title = body.title
    if body.content is not None:
        a.content = body.content
    if body.category is not None:
        a.category = body.category
    if body.tags is not None:
        a.tags = body.tags
    a.updated_at = datetime.now(UTC).isoformat()
    return {"article": a.model_dump(mode="json")}


@app.post("/articles/{article_id}/publish", tags=["articles"])
async def publish_article(request: Request, article_id: str) -> dict:
    await _verify_auth(request)
    a = _get_article(article_id)
    if a.status == "published":
        raise HTTPException(status_code=400, detail="Article already published")
    a.status = "published"
    a.updated_at = datetime.now(UTC).isoformat()
    return {"article": a.model_dump(mode="json")}


@app.delete("/articles/{article_id}", tags=["articles"])
async def delete_article(request: Request, article_id: str) -> dict:
    await _verify_auth(request)
    a = _get_article(article_id)
    _store["articles"] = [x for x in _store["articles"] if x.id != article_id]
    return {"deleted": True, "article_id": article_id}


@app.post("/articles/{article_id}/preview", tags=["articles"])
async def preview_article(request: Request, article_id: str) -> dict:
    await _verify_auth(request)
    a = _get_article(article_id)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{a.title}</title>
<style>body{{font-family:sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem}}
h1{{color:#2563eb}}.meta{{color:#666;font-size:0.9em}}</style></head>
<body><h1>{a.title}</h1>
<p class="meta">Category: {a.category} | Tags: {', '.join(a.tags)} | Status: {a.status}</p>
<p>{a.content}</p></body></html>"""
    return {"html": html, "article_id": a.id, "title": a.title}


# ── Category / Tag endpoints ─────────────────────────────────────────────────


@app.get("/categories", tags=["categorisation"])
async def list_categories(request: Request) -> dict:
    await _verify_auth(request)
    return {"categories": _store["categories"], "total": len(_store["categories"])}


@app.get("/tags", tags=["categorisation"])
async def list_tags(request: Request) -> dict:
    await _verify_auth(request)
    return {"tags": _store["tags"], "total": len(_store["tags"])}


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/healthz", tags=["system"])
async def healthz() -> dict:
    return {"status": "ok", "app": "content-studio"}


# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("examples.demo_app.main:app", host="0.0.0.0", port=8080, reload=True)
