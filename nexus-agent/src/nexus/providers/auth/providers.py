"""Authentication providers: none / api_key / jwt (pluggable OIDC-compatible)."""

from __future__ import annotations

from typing import Any

import structlog

from nexus.providers.auth.base import AuthProvider, Identity

logger = structlog.get_logger("nexus.providers.auth")


class NoAuthProvider(AuthProvider):
    """Passthrough — embedded use behind the application's own auth.

    Returns an anonymous identity so ``ResolverContext`` still carries a
    user id for permission checks (which deployments can tighten later).
    """

    async def authenticate(self, headers: dict[str, str]) -> Identity | None:
        return Identity(user_id="anonymous")


class ApiKeyAuthProvider(AuthProvider):
    """Static API key verification (production-lite; for service-to-service)."""

    def __init__(self, api_key: str, header_name: str = "X-API-Key") -> None:
        self._api_key = api_key
        self._header_name = header_name.lower()

    async def authenticate(self, headers: dict[str, str]) -> Identity | None:
        supplied = headers.get(self._header_name) or headers.get(self._header_name.title())
        if supplied and supplied == self._api_key:
            return Identity(user_id="api-key")
        return None


class JwtAuthProvider(AuthProvider):
    """Standard JWT verification — works with self-issued and OIDC tokens.

    Supports symmetric (HS256/384/512) and asymmetric (RS256/384/512) tokens.
    For asymmetric verification the public key is provided via the
    ``public_key`` PEM string or a JWKS URL (OIDC discovery).
    """

    def __init__(
        self,
        secret: str | None = None,
        algorithm: str = "HS256",
        issuer: str | None = None,
        public_key: str | None = None,
        jwks_url: str | None = None,
    ) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._issuer = issuer
        self._public_key = public_key
        self._jwks_url = jwks_url

    async def authenticate(self, headers: dict[str, str]) -> Identity | None:
        auth_header = headers.get("authorization") or headers.get("Authorization")
        if not auth_header or not auth_header.lower().startswith("bearer "):
            return None
        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            return None
        try:
            payload = await self._decode(token)
        except Exception as exc:
            logger.warning("auth.jwt_invalid", error=str(exc)[:200])
            return None
        return self._identity_from_claims(payload)

    async def _decode(self, token: str) -> dict[str, Any]:
        import jwt

        if self._algorithm.upper().startswith("RS") or self._algorithm.upper().startswith("ES"):
            key: Any = self._public_key
            if not key and self._jwks_url:
                key = await self._fetch_jwks_key(token)
        else:
            key = self._secret
        options = {"verify_aud": False}
        return jwt.decode(
            token,
            key=key,
            algorithms=[self._algorithm],
            issuer=self._issuer,
            options=options,
        )

    async def _fetch_jwks_key(self, token: str) -> Any:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(self._jwks_url)
            resp.raise_for_status()
            data = resp.json()
        keys = data.get("keys", [])
        header = _unverified_header(token)
        kid = header.get("kid")
        for k in keys:
            if kid and k.get("kid") == kid:
                from jwt.algorithms import RSAAlgorithm

                return RSAAlgorithm.from_jwk(k)
        raise ValueError("No matching JWK found")

    def _identity_from_claims(self, claims: dict[str, Any]) -> Identity:
        user_id = str(claims.get("sub") or claims.get("user_id") or "unknown")
        roles = list(claims.get("roles") or claims.get("realm_access", {}).get("roles") or [])
        permissions = list(claims.get("permissions") or [])
        return Identity(user_id=user_id, roles=roles, permissions=permissions, claims=claims)


def _unverified_header(token: str) -> dict[str, Any]:
    import base64
    import json

    parts = token.split(".")
    if len(parts) < 2:
        return {}
    padded = parts[0] + "=" * (-len(parts[0]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return {}
