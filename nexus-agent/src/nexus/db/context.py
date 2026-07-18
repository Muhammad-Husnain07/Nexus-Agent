"""Tenant context propagation via contextvars throughout the async call stack."""

import uuid
from contextvars import ContextVar, Token

_tenant_id_var: ContextVar[uuid.UUID | None] = ContextVar("tenant_id", default=None)


def reset_tenant() -> None:
    """Reset the tenant context to None (useful in test teardown)."""
    _tenant_id_var.set(None)


def set_tenant(tenant_id: uuid.UUID) -> None:
    """Set the current tenant_id for this async context."""
    _tenant_id_var.set(tenant_id)


def get_tenant() -> uuid.UUID | None:
    """Return the current tenant_id or None."""
    return _tenant_id_var.get()


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

    def __enter__(self) -> "TenantContext":
        self._token = _tenant_id_var.set(self._tenant_id)
        return self

    def __exit__(self, *args: object) -> None:
        if self._token is not None:
            _tenant_id_var.reset(self._token)
