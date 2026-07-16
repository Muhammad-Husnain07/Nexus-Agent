"""Nexus Agent FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI

from nexus.api.routes import router
from nexus.config.settings import get_settings
from nexus.llm.provider import ProviderRegistry
from nexus.middleware.auth import AuthMiddleware
from nexus.middleware.tenant import TenantMiddleware
from nexus.observability.logging import setup_logging
from nexus.observability.tracing import setup_tracing
from nexus.redis_client.client import close_redis, init_redis, redis_health_check
from nexus.tools.mcp_server import setup_mcp
from nexus.tools.registry import ToolRegistry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialize services on startup, tear down on shutdown."""
    settings = get_settings()
    setup_logging(settings)
    setup_tracing(settings)
    await init_redis()
    ProviderRegistry.init()
    tool_registry = ToolRegistry()
    setup_mcp(app, tool_registry)
    app.state.tool_registry = tool_registry
    app.state.settings = settings
    yield
    await close_redis()


def create_app() -> FastAPI:
    """Create and return a fully configured FastAPI application instance."""
    app = FastAPI(
        title="Nexus Agent",
        description="Standalone vendor-neutral agentic AI orchestration layer",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness check."""
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        """Readiness check: verify database and Redis connectivity."""
        settings = get_settings()
        checks: dict[str, str] = {}

        try:
            conn = await asyncpg.connect(settings.database.url.replace("+asyncpg", ""))
            await conn.close()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"

        try:
            redis_ok = await redis_health_check()
            checks["redis"] = "ok" if redis_ok else "error: ping failed"
        except Exception as exc:
            checks["redis"] = f"error: {exc}"

        all_ok = all(v == "ok" for v in checks.values())
        return {"status": "ok" if all_ok else "degraded", **checks}

    app.add_middleware(TenantMiddleware)
    app.add_middleware(AuthMiddleware)

    app.include_router(router, prefix="/api/v1")

    return app
