"""Repository base classes for generic and tenant-scoped CRUD."""

from nexus.db.repositories.base import GenericRepository, TenantScopedRepository

__all__ = [
    "GenericRepository",
    "TenantScopedRepository",
]
