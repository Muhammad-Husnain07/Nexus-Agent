"""Database engine, session, models, context, and repositories."""

from nexus.db.base import (
    Base,
    async_session,
    dispose_engine,
    get_engine,
    get_session,
    get_session_factory,
    tenant_table_args,
)
from nexus.db.context import TenantContext, get_tenant, reset_tenant, set_tenant
from nexus.db.models import *  # noqa: F403 — register all models on Base.metadata
from nexus.db.repositories import GenericRepository, TenantScopedRepository

__all__ = [
    "Base",
    "GenericRepository",
    "TenantContext",
    "TenantScopedRepository",
    "async_session",
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_session_factory",
    "get_tenant",
    "reset_tenant",
    "set_tenant",
    "tenant_table_args",
]
