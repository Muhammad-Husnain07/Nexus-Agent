"""Generic and tenant-scoped repository base classes for CRUD operations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.base import Base
from nexus.db.context import get_asserted_tenant, get_tenant


class GenericRepository[T: Base]:
    """Generic CRUD repository for any SQLAlchemy model.

    Usage:
        repo = GenericRepository(session, MyModel)
        instance = await repo.create(field1="val1", field2="val2")
    """

    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        self._session = session
        self._model = model

    async def create(self, **kwargs: Any) -> T:
        """Create and return a new model instance."""
        instance = self._model(**kwargs)
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def get(self, id: uuid.UUID) -> T | None:
        """Retrieve an instance by primary key."""
        return await self._session.get(self._model, id)

    async def find(self, **filters: Any) -> list[T]:
        """Find instances matching keyword filters."""
        stmt = select(self._model).filter_by(**filters)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, id: uuid.UUID, **kwargs: Any) -> T | None:
        """Update an instance by primary key. Returns None if not found."""
        instance = await self.get(id)
        if instance is None:
            return None
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self._session.flush()
        return instance

    async def delete(self, id: uuid.UUID) -> bool:
        """Delete an instance by primary key. Returns True if deleted."""
        instance = await self.get(id)
        if instance is None:
            return False
        await self._session.delete(instance)
        await self._session.flush()
        return True


class TenantScopedRepository[T: Base](GenericRepository[T]):
    """Repository that automatically scopes all operations to the current tenant.

    Reads tenant_id from TenantContext (contextvars) and injects it into
    every query filter and every create call.  Also performs a defense-in-depth
    assertion that the context tenant matches the auth-verified tenant.
    """

    def _assert_tenant(self) -> None:
        """Raise RuntimeError if the context tenant diverges from the asserted tenant.

        This is a belt-and-suspenders check against any future code path that
        sets tenant context incorrectly.
        """
        active = get_tenant()
        asserted = get_asserted_tenant()
        if asserted is not None and active is not None and active != asserted:
            raise RuntimeError(
                f"Tenant mismatch: context tenant {active} != asserted tenant {asserted}"
            )

    async def create(self, **kwargs: Any) -> T:
        """Create a new instance with tenant_id from context."""
        if "tenant_id" not in kwargs:
            tenant_id = get_tenant()
            if tenant_id is not None:
                kwargs["tenant_id"] = tenant_id
        return await super().create(**kwargs)

    async def get(self, id: uuid.UUID) -> T | None:
        """Retrieve an instance scoped to the current tenant."""
        self._assert_tenant()
        stmt = (
            select(self._model)
            .where(self._model.id == id)
            .where(self._model.tenant_id == get_tenant())
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find(self, **filters: Any) -> list[T]:
        """Find instances with auto-injected tenant_id filter."""
        self._assert_tenant()
        if "tenant_id" not in filters:
            tenant_id = get_tenant()
            if tenant_id is not None:
                filters["tenant_id"] = tenant_id
        return await super().find(**filters)
