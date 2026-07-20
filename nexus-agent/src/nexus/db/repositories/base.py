"""Generic repository base class for CRUD operations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.base import Base



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
        await self._session.refresh(instance)
        return instance

    async def delete(self, id: uuid.UUID) -> bool:
        """Delete an instance by primary key. Returns True if deleted."""
        instance = await self.get(id)
        if instance is None:
            return False
        await self._session.delete(instance)
        await self._session.flush()
        return True



