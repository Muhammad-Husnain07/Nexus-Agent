"""ASGI middleware for API key and JWT authentication."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import structlog
from jose import JWTError, jwt
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nexus.config.settings import get_settings
from nexus.db.base import async_session
from nexus.db.models.user import ApiKey

logger = structlog.get_logger("nexus.middleware.auth")

BYPASS_PATHS = {"/healthz", "/readyz", "/docs", "/redoc", "/openapi.json"}


class AuthMiddleware(BaseHTTPMiddleware):
    """Authenticate requests via ``Authorization: Bearer <JWT>`` or ``X-API-Key``.

    Sets ``request.state.user_id`` and ``request.state.user_role`` from the
    resolved identity.  Invalid credentials and expired keys are logged but
    do not block the request — enforcement is handled per-endpoint via
    ``require_permission()``.
    """

    async def dispatch(self, request: Request, call_next: callable) -> Response:
        request.state.user_id = None
        request.state.user_role = None

        # Skip auth for public endpoints
        if request.url.path in BYPASS_PATHS:
            return await call_next(request)

        settings = get_settings()

        # Try Bearer JWT first
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = jwt.decode(
                    token,
                    settings.auth.jwt_secret.get_secret_value(),
                    algorithms=[settings.auth.jwt_algorithm],
                )
                user_id = payload.get("sub")
                if user_id:
                    request.state.user_id = uuid.UUID(user_id)
                    request.state.user_role = payload.get("role")
            except (JWTError, ValueError):
                logger.warning("jwt_validation_failed")
            return await call_next(request)

        # Fall back to API key
        header_name = settings.auth.api_key_header_name
        raw = request.headers.get(header_name)

        if raw:
            key_hash = hashlib.sha256(raw.strip().encode()).hexdigest()
            try:
                async with async_session() as session:
                    stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
                    result = await session.execute(stmt)
                    api_key = result.scalar_one_or_none()
                    if api_key is not None:
                        # Check expiry
                        if api_key.expires_at and api_key.expires_at < datetime.now(UTC):
                            logger.warning("api_key_expired")
                            return await call_next(request)

                        request.state.user_id = api_key.user_id
                        request.state.user_role = api_key.role_hint
                        request.state.api_key_scopes = api_key.scopes
                    else:
                        logger.warning("invalid_api_key")
            except Exception:
                logger.exception("auth_middleware_error")

        return await call_next(request)
