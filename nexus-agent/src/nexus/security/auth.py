"""JWT token creation and verification (no login routes)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from nexus.config.settings import get_settings
from nexus.errors.base import UnauthorizedError


def create_access_token(
    user_id: uuid.UUID,
    role: str,
    tenant_id: uuid.UUID | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    settings = get_settings()
    expire = expires_delta or timedelta(minutes=settings.auth.access_token_ttl_minutes)
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "iss": settings.auth.jwt_issuer,
        "aud": settings.auth.jwt_audience,
        "iat": now,
        "exp": now + expire,
        "type": "access",
    }
    if tenant_id is not None:
        payload["tid"] = str(tenant_id)
    return jwt.encode(payload, settings.auth.jwt_secret.get_secret_value(), algorithm=settings.auth.jwt_algorithm)


def create_refresh_token(user_id: uuid.UUID, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    expire = expires_delta or timedelta(days=settings.auth.refresh_token_ttl_days)
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iss": settings.auth.jwt_issuer,
        "aud": settings.auth.jwt_audience,
        "iat": now,
        "exp": now + expire,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.auth.jwt_secret.get_secret_value(), algorithm=settings.auth.jwt_algorithm)


async def verify_jwt(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.auth.jwt_secret.get_secret_value(),
            algorithms=[settings.auth.jwt_algorithm],
            audience=settings.auth.jwt_audience,
        )
    except JWTError as exc:
        raise UnauthorizedError(f"Invalid token: {exc}") from exc
    if payload.get("iss") != settings.auth.jwt_issuer:
        raise UnauthorizedError("Invalid token issuer")
    return payload
