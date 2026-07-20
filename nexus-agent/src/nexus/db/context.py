"""Tenant ID propagation via contextvar (passthrough — always returns default)."""
from __future__ import annotations

import uuid
from contextvars import ContextVar

from nexus.utils.constants import DEFAULT_TENANT_ID_STR

_tenant_id_var: ContextVar[uuid.UUID | None] = ContextVar("tenant_id", default=None)


def reset_tenant() -> None:
    _tenant_id_var.set(None)


def set_tenant(tenant_id: uuid.UUID) -> None:
    _tenant_id_var.set(tenant_id)


def get_tenant() -> uuid.UUID:
    val = _tenant_id_var.get()
    if val is None:
        val = uuid.UUID(DEFAULT_TENANT_ID_STR)
    return val
