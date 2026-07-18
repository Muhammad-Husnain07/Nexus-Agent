"""Tenant context propagation via contextvars throughout the async call stack."""

import uuid
from contextvars import ContextVar, Token

_tenant_id_var: ContextVar[uuid.UUID | None] = ContextVar("tenant_id", default=None)
_asserted_tenant_id_var: ContextVar[uuid.UUID | None] = ContextVar("asserted_tenant_id", default=None)


def reset_tenant() -> None:
    """Reset the tenant context to None (useful in test teardown)."""
    _tenant_id_var.set(None)
    _asserted_tenant_id_var.set(None)


def set_tenant(tenant_id: uuid.UUID) -> None:
    """Set the current tenant_id for this async context."""
    _tenant_id_var.set(tenant_id)


def get_tenant() -> uuid.UUID | None:
    """Return the current tenant_id or None."""
    return _tenant_id_var.get()


def set_asserted_tenant(tenant_id: uuid.UUID) -> None:
    """Set the asserted (auth-verified) tenant_id for defense-in-depth."""
    _asserted_tenant_id_var.set(tenant_id)


def get_asserted_tenant() -> uuid.UUID | None:
    """Return the asserted tenant_id or None."""
    return _asserted_tenant_id_var.get()


def reset_asserted_tenant() -> None:
    """Reset the asserted tenant context."""
    _asserted_tenant_id_var.set(None)


class TenantContext:
    """Context manager that scopes all operations to a tenant.

    Usage:
        with TenantContext(tenant_id=some_uuid):
            # all repository calls auto-filter by this tenant
            ...
    """

    def __init__(self, tenant_id: uuid.UUID) -> None:
        self._tenant_id = tenant_id
        self._token: Token[uuid.UUID | None] | None = None
        self._asserted_token: Token[uuid.UUID | None] | None = None

    def __enter__(self) -> "TenantContext":
        self._token = _tenant_id_var.set(self._tenant_id)
        self._asserted_token = _asserted_tenant_id_var.set(self._tenant_id)
        return self

    def __exit__(self, *args: object) -> None:
        if self._asserted_token is not None:
            _asserted_tenant_id_var.reset(self._asserted_token)
        if self._token is not None:
            _tenant_id_var.reset(self._token)
