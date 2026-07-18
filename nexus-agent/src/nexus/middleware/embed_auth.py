"""ASGI middleware for embed token authentication and domain validation.

Validates embed tokens from query parameters or headers, enforces domain
whitelist (CORS), applies per-token rate limiting, and injects embed
context into request state.
"""

from __future__ import annotations

import fnmatch
from typing import Any

import structlog
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nexus.db.base import async_session
from nexus.db.models.embed import EmbedConfig
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.rate_limiter import TokenBucketRateLimiter

logger = structlog.get_logger("nexus.middleware.embed_auth")

EMBED_PATHS = ("/api/v1/embeds", "/embed")
BYPASS_PATHS = {"/healthz", "/readyz", "/docs", "/redoc", "/openapi.json"}


def _extract_token(request: Request) -> str | None:
    """Extract embed token from query param or header."""
    token = request.query_params.get("token")
    if token:
        return token
    token = request.headers.get("X-Embed-Token")
    if token:
        return token
    return None


def _is_embed_request(request: Request) -> bool:
    """Check if the request targets an embed-related path."""
    path = request.url.path
    return path.startswith(EMBED_PATHS) or path.startswith(EMBED_PATHS[1])


def _check_domain(origin: str | None, allowed_domains: list[str]) -> bool:
    """Validate an Origin header against the allowed domains whitelist.

    Supports glob patterns via ``fnmatch``.
    """
    if not origin:
        return True  # No Origin header → allow (browser will still enforce CORS)
    if "*" in allowed_domains:
        return True
    host = origin.lower().replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
    return any(fnmatch.fnmatch(host, pattern.lower()) for pattern in allowed_domains)


class EmbedTokenAuth(BaseHTTPMiddleware):
    """Validate embed tokens from query params or headers.

    Middleware pipeline:
    1. Skip non-embed paths and bypass paths
    2. Extract token from ``?token=`` query param or ``X-Embed-Token`` header
    3. Look up token in DB — reject if not found or revoked
    4. Validate ``Origin`` header against ``allowed_domains`` whitelist
    5. Apply per-token rate limiting via ``TokenBucketRateLimiter``
    6. Inject ``request.state.embed_id`` and ``request.state.embed_config``
    7. Log usage for analytics
    """

    def __init__(self, app: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__(app, *args, **kwargs)
        self._rate_limiters: dict[str, TokenBucketRateLimiter] = {}

    async def dispatch(self, request: Request, call_next: Any) -> Response:  # noqa: PLR0911, PLR0912, PLR0915
        # Bypass health check / docs paths
        if request.url.path in BYPASS_PATHS:
            return await call_next(request)

        # Only process embed paths
        if not _is_embed_request(request):
            return await call_next(request)

        token = _extract_token(request)
        if not token:
            # No embed token — let normal auth handle it (will likely 401)
            return await call_next(request)

        # DB lookup
        embed_config = await self._lookup_embed(token)
        if embed_config is None:
            logger.warning("embed.token_invalid", token_prefix=token[:12])
            return Response(
                status_code=403,
                content='{"detail":"Invalid or revoked embed token"}',
                media_type="application/json",
            )

        # Domain validation
        origin = request.headers.get("Origin")
        if not _check_domain(origin, embed_config.allowed_domains):
            logger.warning(
                "embed.domain_blocked",
                embed_id=str(embed_config.id),
                origin=origin,
            )
            return Response(
                status_code=403,
                content='{"detail":"Domain not allowed"}',
                media_type="application/json",
            )

        # Rate limiting
        redis = get_redis_client()
        if redis is not None:
            rl_key = f"embed:{token}:rl"
            if rl_key not in self._rate_limiters:
                self._rate_limiters[rl_key] = TokenBucketRateLimiter(
                    redis_client=redis,
                    rate=embed_config.rate_limit / 60.0,
                    capacity=float(embed_config.rate_limit),
                )
            try:
                await self._rate_limiters[rl_key].acquire(rl_key, raise_on_limit=True)
            except Exception:
                logger.warning("embed.rate_limited", embed_id=str(embed_config.id))
                return Response(
                    status_code=429,
                    content='{"detail":"Rate limit exceeded"}',
                    media_type="application/json",
                    headers={"Retry-After": "60"},
                )

        # Inject embed context into request state
        request.state.embed_id = embed_config.id
        request.state.embed_config = embed_config
        request.state.embed_token = token
        request.state.tenant_id = embed_config.tenant_id

        # Log usage
        logger.info(
            "embed.access",
            embed_id=str(embed_config.id),
            origin=origin or "none",
            path=request.url.path,
        )

        # Analytics counter (fire-and-forget)
        if embed_config.analytics_enabled and redis is not None:
            try:
                await redis.incr(f"embed:messages:{token}")
                await redis.expire(f"embed:messages:{token}", 86400)
            except Exception as analytics_exc:
                logger.debug("embed.analytics_incr_failed", error=str(analytics_exc))

        response = await call_next(request)

        # Dynamic CORS: echo back the validated origin
        if origin and _check_domain(origin, embed_config.allowed_domains):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Authorization, X-Embed-Token"
            )

        return response

    @staticmethod
    async def _lookup_embed(token: str) -> EmbedConfig | None:
        """Look up a non-revoked embed config by token."""
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(EmbedConfig).where(
                        EmbedConfig.token == token,
                        EmbedConfig.is_revoked == False,  # noqa: E712
                    )
                )
                return result.scalar_one_or_none()
        except Exception as exc:
            logger.warning("embed.lookup_failed", error=str(exc))
            return None
