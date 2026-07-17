"""Nexus Agent FastAPI application factory with full middleware stack.

Creates a configured ``FastAPI`` instance with:
- CORS, TrustedHost, RequestID middleware
- Structured request/response logging via structlog
- Global exception handler mapping domain exceptions to HTTP responses
- Graceful shutdown: drain middleware + SSE/agent-run tracking
- All routers mounted under ``/api/v1``
- MCP server at ``/mcp``
- OpenAPI documentation with auth schemes
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator, Set
from contextlib import asynccontextmanager

import asyncpg
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse
from starlette.types import ASGIApp

from nexus.api.routes import router
from nexus.config.settings import get_settings
from nexus.errors import ErrorHandlerMiddleware
from nexus.llm.provider import ProviderRegistry
from nexus.middleware.auth import AuthMiddleware
from nexus.middleware.tenant import TenantMiddleware
from nexus.observability.logging import setup_logging
from nexus.observability.tracing import setup_tracing
from nexus.redis_client.client import close_redis, init_redis, redis_health_check
from nexus.security.rate_limit import TieredRateLimitMiddleware
from nexus.tools.mcp_server import setup_mcp
from nexus.tools.registry import ToolRegistry

logger = structlog.get_logger("nexus.api")


# ---------------------------------------------------------------------------
# Request ID middleware
# ---------------------------------------------------------------------------


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Propagate or generate an ``X-Request-ID`` header for every request."""

    async def dispatch(self, request: Request, call_next: callable) -> StarletteResponse:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = req_id

        response: StarletteResponse = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


# ---------------------------------------------------------------------------
# Structured logging middleware
# ---------------------------------------------------------------------------


class LoggingMiddleware(BaseHTTPMiddleware):
    """Log structured request/response summaries via structlog."""

    async def dispatch(self, request: Request, call_next: callable) -> StarletteResponse:
        req_id = getattr(request.state, "request_id", None)
        logger.info(
            "request.started",
            method=request.method,
            path=request.url.path,
            req_id=req_id,
        )
        response: StarletteResponse = await call_next(request)
        logger.info(
            "request.completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            req_id=req_id,
        )
        return response


# (Global exception handling is provided by ErrorHandlerMiddleware)


# ---------------------------------------------------------------------------
# Graceful shutdown — drain middleware
# ---------------------------------------------------------------------------


DRAIN_PATHS = {"/healthz", "/readyz", "/metrics"}


class DrainMiddleware(BaseHTTPMiddleware):
    """Reject new requests during graceful shutdown, except health/metrics.

    Once ``app.state.draining`` is set to ``True`` by the lifespan shutdown
    handler, this middleware returns 503 for all non-essential paths so that
    the load balancer stops routing traffic.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: callable) -> Response:
        if getattr(request.app.state, "draining", False):
            if request.url.path not in DRAIN_PATHS:
                return Response(
                    status_code=503,
                    content='{"detail":"Server is shutting down","error_code":"SHUTTING_DOWN"}',
                    media_type="application/json",
                )
        return await call_next(request)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize services on startup, tear down on shutdown."""
    settings = get_settings()
    setup_logging(settings)
    setup_tracing(settings)
    await init_redis()
    ProviderRegistry.init()
    tool_registry = ToolRegistry()
    setup_mcp(app, tool_registry)
    app.state.tool_registry = tool_registry
    app.state.settings = settings
    app.state.draining = False
    app.state.active_agent_runs = 0
    app.state.active_sse_connections: set = set()

    from nexus.utils.scheduler import start_scheduler, stop_scheduler

    await start_scheduler()

    yield

    # ── Graceful shutdown ──────────────────────────────────────────────
    app.state.draining = True
    logger.warning(
        "shutdown.draining",
        reason="SIGTERM received",
        active_runs=app.state.active_agent_runs,
        open_sse=len(app.state.active_sse_connections),
    )

    # Close all SSE connections so clients reconnect elsewhere
    for conn in list(app.state.active_sse_connections):
        try:
            conn.close()
        except Exception:
            pass

    # Wait for in-flight agent runs up to 30 seconds
    if app.state.active_agent_runs > 0:
        deadline = time.monotonic() + 30
        while app.state.active_agent_runs > 0 and time.monotonic() < deadline:
            await asyncio.sleep(0.5)
        remaining = app.state.active_agent_runs
        if remaining > 0:
            logger.warning("shutdown.force_exit", active_runs=remaining)

    await stop_scheduler()
    await close_redis()
    from nexus.db.base import dispose_engine

    await dispose_engine()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Create a fully configured FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title="Nexus Agent API",
        description="Standalone vendor-neutral agentic AI orchestration layer.  "
        "Provides conversational AI via SSE streaming, WebSocket, and synchronous "
        "endpoints, with HITL approval, tool registry, and long-term memory.",
        version="0.1.0",
        lifespan=lifespan,
        contact={
            "name": "Nexus Agent Team",
            "url": "https://github.com/anomalyco/nexus-agent",
        },
        license_info={
            "name": "MIT",
            "url": "https://opensource.org/licenses/MIT",
        },
        servers=[
            {"url": "http://localhost:8000", "description": "Local development"},
        ],
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── Health checks ────────────────────────────────────────────────────
    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, str]:
        """Liveness check."""
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/readyz", tags=["system"])
    async def readyz(request: Request) -> dict[str, str]:
        """Readiness check: verify database and Redis connectivity.

        Returns ``draining`` status when the server is shutting down,
        so load balancers can stop routing traffic.
        """
        if getattr(request.app.state, "draining", False):
            return {"status": "draining"}

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

    # ── Middleware stack ──────────────────────────────────────────────────
    # Order: outermost first
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # TrustedHost — if configured
    if settings.server.cors_origins != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.server.cors_origins)

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(TenantMiddleware)
    app.add_middleware(TieredRateLimitMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(ErrorHandlerMiddleware)

    # ── Drain middleware (order: after auth, before security headers) ─────
    app.add_middleware(DrainMiddleware)

    # ── Security headers middleware ───────────────────────────────────────
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: callable) -> StarletteResponse:
        response: StarletteResponse = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/docs") or request.url.path.startswith("/redoc"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'"
            )
        return response

    # ── Routers ───────────────────────────────────────────────────────────
    app.include_router(router, prefix="/api/v1")

    from nexus.observability.metrics import router as metrics_router

    app.include_router(metrics_router)

    # ── OpenAPI auth schemes ──────────────────────────────────────────────
    # Set after app creation to avoid FastAPI inspecting during init
    if app.openapi_schema is not None:
        app.openapi_schema = None  # force rebuild

    def _custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        schema = app._generate_openapi()  # type: ignore[attr-defined]
        if schema:
            schema.setdefault("components", {})
            schema["components"]["securitySchemes"] = {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": "JWT token from the auth endpoint",
                },
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                    "description": "API key from the developer dashboard",
                },
            }
            schema["security"] = [{"BearerAuth": []}, {"ApiKeyAuth": []}]
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = _custom_openapi  # type: ignore[assignment]

    return app
