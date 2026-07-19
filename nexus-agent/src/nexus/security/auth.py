"""JWT issuance, API key management, token refresh/revocation, and auth endpoints."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from argon2 import PasswordHasher
from fastapi import APIRouter, Body, Depends, HTTPException
from jose import JWTError, jwt
from sqlalchemy import select

from nexus.config.settings import get_settings
from nexus.db.base import async_session
from nexus.db.models.user import User
from nexus.errors import UnauthorizedError
from nexus.redis_client.client import get_redis_client
from nexus.security.rbac import require_user

logger = structlog.get_logger("nexus.security.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

_ph = PasswordHasher()

# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def create_access_token(
    user_id: uuid.UUID,
    role: str,
    tenant_id: uuid.UUID | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Issue a short-lived JWT access token.

    Args:
        user_id: The user's UUID.
        role: RBAC role string.
        tenant_id: Optional tenant UUID.
        expires_delta: Token lifetime (defaults to ``access_token_ttl_minutes``).

    Returns:
        Encoded JWT string.
    """
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
    return jwt.encode(
        payload,
        settings.auth.jwt_secret.get_secret_value(),
        algorithm=settings.auth.jwt_algorithm,
    )


def create_refresh_token(user_id: uuid.UUID, expires_delta: timedelta | None = None) -> str:
    """Issue a long-lived JWT refresh token.

    The token is also stored in Redis so it can be revoked.
    """
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
    token = jwt.encode(
        payload,
        settings.auth.jwt_secret.get_secret_value(),
        algorithm=settings.auth.jwt_algorithm,
    )
    # Store in Redis for revocation support
    redis = get_redis_client()
    if redis is not None:
        import asyncio

        try:
            asyncio.ensure_future(_store_refresh_token(redis, payload["jti"], expire))
        except Exception:
            pass
    return token


async def _store_refresh_token(redis, jti: str, expire: timedelta) -> None:
    """Store the refresh token's JTI in Redis for revocation checks."""
    try:
        await redis.set(f"refresh:{jti}", "1", ex=int(expire.total_seconds()))
    except Exception as exc:
        logger.warning("refresh_token_store_failed", error=str(exc))


async def verify_jwt(token: str) -> dict[str, Any]:
    """Decode and validate a JWT, checking the revocation denylist.

    Returns:
        The decoded payload dict.

    Raises:
        UnauthorizedError: If the token is invalid, expired, or revoked.
    """
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.auth.jwt_secret.get_secret_value(),
            algorithms=[settings.auth.jwt_algorithm],
            audience=settings.auth.jwt_audience,
        )
    except JWTError as exc:
        raise UnauthorizedError(f"Invalid token: {exc}") from exc

    # Validate issuer
    if payload.get("iss") != settings.auth.jwt_issuer:
        raise UnauthorizedError("Invalid token issuer")

    # Check revocation for refresh tokens
    if payload.get("type") == "refresh" and payload.get("jti"):
        redis = get_redis_client()
        if redis is not None:
            exists = await redis.get(f"refresh:{payload['jti']}")
            if exists is None:
                raise UnauthorizedError("Refresh token has been revoked")
    return payload


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


def generate_api_key() -> str:
    """Generate a cryptographically random API key with the ``nxs_`` prefix.

    The key is 32 bytes (256 bits) of randomness, base64url-encoded,
    prefixed with ``nxs_`` for identifiability.
    """
    raw = secrets.token_urlsafe(32)
    return f"nxs_{raw}"


async def hash_api_key(key: str) -> str:
    """Hash an API key using argon2id for storage.

    Args:
        key: The plaintext API key (``nxs_...``).

    Returns:
        The argon2 hash string suitable for DB storage.
    """
    return _ph.hash(key)


async def verify_api_key(key: str, key_hash: str) -> bool:
    """Verify a plaintext API key against its stored argon2 hash.

    Uses constant-time comparison via argon2's built-in verification.
    """
    try:
        return _ph.verify(key_hash, key)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login")
async def login(email: str = Body(..., embed=True)) -> dict[str, str]:
    """Issue access + refresh tokens (stub — no password verification yet).

    TODO: Add credential verification (password hash, OAuth, etc.) when
    the User model includes a password_hash column.
    """
    async with async_session() as session:
        stmt = select(User).where(User.email == email)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    access_token = create_access_token(user.id, user.role, user.tenant_id)
    refresh_token = create_refresh_token(user.id)
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/refresh")
async def refresh_token(refresh_token: str) -> dict[str, str]:
    """Issue a new access token using a valid refresh token."""
    payload = await verify_jwt(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=400, detail="Invalid token type")

    user_id = uuid.UUID(payload["sub"])
    async with async_session() as session:
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    access_token = create_access_token(user.id, user.role, user.tenant_id)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/revoke")
async def revoke_token(
    refresh_token: str,
    current_user: tuple[uuid.UUID, Any] = Depends(require_user),
) -> dict[str, str]:
    """Revoke a refresh token by removing it from the Redis denylist.

    The caller must provide the ``refresh_token`` string.  The token's
    ``jti`` (JWT ID) is extracted from the payload and deleted from
    Redis, making it impossible to use for future refresh calls.

    Requires authentication — the caller must be the token owner.
    """
    try:
        payload = await verify_jwt(refresh_token)
    except UnauthorizedError as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired refresh token") from exc

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=400, detail="Not a refresh token")

    token_user_id = uuid.UUID(payload["sub"])
    if token_user_id != current_user[0]:
        raise HTTPException(status_code=403, detail="Cannot revoke another user's token")

    jti = payload.get("jti")
    if jti:
        redis = get_redis_client()
        if redis is not None:
            await redis.delete(f"refresh:{jti}")
            logger.info("token.revoked", user_id=str(current_user[0]), jti=jti)

    return {"status": "ok"}
