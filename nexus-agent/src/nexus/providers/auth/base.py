"""Authentication provider interface — pluggable identity verification.

Modes:
- ``none`` — passthrough (embedded use behind the app's own auth)
- ``api_key`` — static key verification via header
- ``jwt`` — standard JWT verification (self-issued or OIDC-issued tokens)

The orchestrator depends on this ABC; providers are pluggable per deployment
(Auth0, Keycloak, Azure AD, Okta, Google, self-issued) without core changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Identity:
    """Verified caller identity injected into the request context."""

    def __init__(
        self,
        user_id: str = "anonymous",
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        claims: dict[str, Any] | None = None,
    ) -> None:
        self.user_id = user_id
        self.roles = roles or []
        self.permissions = permissions or []
        self.claims = claims or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "roles": self.roles,
            "permissions": self.permissions,
        }


class AuthProvider(ABC):
    """Abstract identity verifier."""

    @abstractmethod
    async def authenticate(self, headers: dict[str, str]) -> Identity | None:
        """Return an Identity for the request headers, or None if unauthenticated.

        ``None`` means "no valid identity" — the middleware decides whether
        that is allowed (mode none) or rejected (modes api_key/jwt).
        """
