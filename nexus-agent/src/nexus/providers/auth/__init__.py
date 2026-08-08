"""Auth provider factory — pluggable mode selection."""

from __future__ import annotations

from nexus.config.settings import get_settings
from nexus.providers.auth.base import AuthProvider, Identity  # noqa: F401

_provider: AuthProvider | None = None


def get_auth_provider() -> AuthProvider:
    """Return the configured auth provider (cached singleton)."""
    global _provider  # noqa: PLW0603
    if _provider is not None:
        return _provider
    settings = get_settings().auth
    mode = settings.mode

    if mode == "none":
        from nexus.providers.auth.providers import NoAuthProvider

        _provider = NoAuthProvider()
    elif mode == "api_key":
        import os

        key = os.environ.get("NEXUS_AUTH__API_KEY", "")
        if not key:
            raise RuntimeError(
                "auth.mode=api_key requires NEXUS_AUTH__API_KEY to be set"
            )
        from nexus.providers.auth.providers import ApiKeyAuthProvider

        _provider = ApiKeyAuthProvider(api_key=key, header_name=settings.api_key_header)
    elif mode == "jwt":
        import os

        secret = os.environ.get("NEXUS_AUTH__JWT_SECRET", "")
        from nexus.providers.auth.providers import JwtAuthProvider

        _provider = JwtAuthProvider(
            secret=secret or None,
            algorithm=settings.jwt_algorithm,
            issuer=settings.jwt_issuer,
            public_key=os.environ.get("NEXUS_AUTH__JWT_PUBLIC_KEY"),
            jwks_url=os.environ.get("NEXUS_AUTH__JWKS_URL"),
        )
    else:
        raise ValueError(f"Unsupported auth mode: {mode}")
    return _provider
