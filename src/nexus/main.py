"""Nexus Agent FastAPI application factory.

Delegates to ``nexus.api.main.create_app()`` for the full middleware stack,
routers, and OpenAPI configuration.  This file provides a backward-compatible
entry point for ``uvicorn nexus.main:app``.
"""

from nexus.api.main import create_app

app = create_app()
"""FastAPI application instance — importable by uvicorn."""
