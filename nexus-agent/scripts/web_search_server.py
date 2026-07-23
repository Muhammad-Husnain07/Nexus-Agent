"""Web Search Proxy Server — local API that bridges to DuckDuckGo.

Provides GET, POST, PUT, PATCH, DELETE endpoints for tool testing.
Runs on http://localhost:8081.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from duckduckgo_search import DDGS
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI(title="Web Search Proxy", version="1.0.0")

# ── In-memory store for bookmarks ──────────────────────────────────────────
_bookmarks: dict[str, dict[str, Any]] = {}
_search_counter = 0


class SearchResult(BaseModel):
    query: str
    results: list[dict[str, str]]
    result_count: int
    timestamp: str


class BookmarkCreate(BaseModel):
    url: str = Field(description="Bookmark URL")
    title: str = Field(description="Bookmark title")
    tags: list[str] = Field(default_factory=list, description="Tags")
    description: str = Field(default="", description="Description")


class BookmarkUpdate(BaseModel):
    url: str = Field(description="New URL")
    title: str = Field(description="New title")
    tags: list[str] = Field(default_factory=list, description="New tags")
    description: str = Field(default="", description="New description")


class BookmarkPatch(BaseModel):
    title: str | None = Field(default=None, description="Updated title")
    tags: list[str] | None = Field(default=None, description="Updated tags")
    description: str | None = Field(default=None, description="Updated description")


class BookmarkOut(BaseModel):
    id: str
    url: str
    title: str
    tags: list[str]
    description: str
    created_at: str
    updated_at: str


# ── GET: Web Search ────────────────────────────────────────────────────────

@app.get("/search", response_model=SearchResult)
async def web_search(q: str = Query(..., description="Search query"), max_results: int = Query(5, le=20)):
    """Search the web using DuckDuckGo."""
    global _search_counter
    _search_counter += 1
    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, lambda: list(
            DDGS().text(keywords=q, region="wt-wt", safesearch="off", max_results=max_results)
        ))
        formatted = [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in results
        ]
        return SearchResult(
            query=q, results=formatted, result_count=len(formatted),
            timestamp=datetime.now(UTC).isoformat(),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Search failed: {exc}")


# ── POST: Create Bookmark ──────────────────────────────────────────────────

@app.post("/bookmarks", status_code=201, response_model=BookmarkOut)
async def create_bookmark(data: BookmarkCreate):
    """Create a new bookmark."""
    bid = str(uuid.uuid4())[:8]
    now = datetime.now(UTC).isoformat()
    _bookmarks[bid] = {
        "id": bid, "url": data.url, "title": data.title,
        "tags": data.tags, "description": data.description,
        "created_at": now, "updated_at": now,
    }
    return _bookmarks[bid]


# ── PUT: Full Update Bookmark ──────────────────────────────────────────────

@app.put("/bookmarks/{bookmark_id}", response_model=BookmarkOut)
async def update_bookmark(bookmark_id: str, data: BookmarkUpdate):
    """Replace all fields of an existing bookmark."""
    if bookmark_id not in _bookmarks:
        raise HTTPException(404, f"Bookmark {bookmark_id} not found")
    entry = _bookmarks[bookmark_id]
    entry["url"] = data.url
    entry["title"] = data.title
    entry["tags"] = list(data.tags)
    entry["description"] = data.description
    entry["updated_at"] = datetime.now(UTC).isoformat()
    _bookmarks[bookmark_id] = entry
    return entry


# ── PATCH: Partial Update Bookmark ─────────────────────────────────────────

@app.patch("/bookmarks/{bookmark_id}", response_model=BookmarkOut)
async def patch_bookmark(bookmark_id: str, data: BookmarkPatch):
    """Partially update a bookmark."""
    if bookmark_id not in _bookmarks:
        raise HTTPException(404, f"Bookmark {bookmark_id} not found")
    entry = _bookmarks[bookmark_id]
    if data.title is not None:
        entry["title"] = data.title
    if data.tags is not None:
        entry["tags"] = list(data.tags)
    if data.description is not None:
        entry["description"] = data.description
    entry["updated_at"] = datetime.now(UTC).isoformat()
    _bookmarks[bookmark_id] = entry
    return entry


# ── DELETE: Delete Bookmark ────────────────────────────────────────────────

@app.delete("/bookmarks/{bookmark_id}", status_code=204)
async def delete_bookmark(bookmark_id: str):
    """Permanently delete a bookmark."""
    if bookmark_id not in _bookmarks:
        raise HTTPException(404, f"Bookmark {bookmark_id} not found")
    del _bookmarks[bookmark_id]
    return None


# ── Utility endpoint ───────────────────────────────────────────────────────

@app.get("/bookmarks", response_model=list[BookmarkOut])
async def list_bookmarks():
    """List all bookmarks."""
    return list(_bookmarks.values())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
