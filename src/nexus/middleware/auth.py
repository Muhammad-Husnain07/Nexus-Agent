"""ASGI middleware for API key authentication."""

from __future__ import annotations

import hashlib
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nexus.config.settings import get_settings
from nexus.db.base import async_session
from nexus.db.models.user import ApiKey

logger = structlog.get_logger("nexus.middleware.auth")


class AuthMiddleware(BaseHTTPMiddleware):
    """Authenticate requests via ``X-API-Key`` header.

    Looks up the key hash in the ``ApiKey`` table and attaches the
    associated ``user_id`` to ``request.state.user_id``.

    If no key is provided, the request proceeds as anonymous
    (``request.state.user_id`` is ``None``).  Invalid keys are logged
    but do not block the request (enforcement is handled per-endpoint).
    """

    async def dispatch(self, request: Request, call_next: callable) -> Response:  # type: ignore[type-arg]
        request.state.user_id = None

        header_name = get_settings().auth.api_key_header_name
        raw = request.headers.get(header_name)

        if raw:
            key_hash = hashlib.sha256(raw.strip().encode()).hexdigest()
            try:
                async with async_session() as session:
                    stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
                    result = await session.execute(stmt)
                    api_key = result.scalar_one_or_none()
                    if api_key is not None:
                        request.state.user_id = api_key.tenant_id
                    else:
                        logger.warning("invalid_api_key")
            except Exception:
                logger.exception("auth_middleware_error")

        return await call_next(request)
