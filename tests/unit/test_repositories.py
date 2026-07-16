"""Unit tests for GenericRepository and TenantScopedRepository."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db.base import Base
from nexus.db.context import set_tenant
from nexus.db.repositories.base import GenericRepository, TenantScopedRepository


class _TestModel(Base):
    """Minimal SQLAlchemy model for repository testing."""

    __tablename__ = "_test_model"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    name: Mapped[str] = mapped_column(String(50), default="")


@pytest.mark.asyncio
async def test_generic_repository_create(mock_session: MagicMock) -> None:
    repo = GenericRepository(mock_session, _TestModel)
    instance = await repo.create(name="test")

    mock_session.add.assert_called_once()
    mock_session.flush.assert_awaited_once()
    assert instance.name == "test"


@pytest.mark.asyncio
async def test_generic_repository_get_found(mock_session: MagicMock) -> None:
    expected = _TestModel()
    mock_session.get.return_value = expected

    repo = GenericRepository(mock_session, _TestModel)
    result = await repo.get(expected.id)

    mock_session.get.assert_awaited_once_with(_TestModel, expected.id)
    assert result is expected


@pytest.mark.asyncio
async def test_generic_repository_get_not_found(mock_session: MagicMock) -> None:
    mock_session.get.return_value = None

    repo = GenericRepository(mock_session, _TestModel)
    result = await repo.get(uuid.uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_generic_repository_find(mock_session: MagicMock) -> None:
    obj1 = _TestModel(tenant_id=uuid.uuid4())
    obj2 = _TestModel(tenant_id=uuid.uuid4())
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [obj1, obj2]
    mock_session.execute.return_value = mock_result

    repo = GenericRepository(mock_session, _TestModel)
    results = await repo.find(tenant_id=obj1.tenant_id)

    mock_session.execute.assert_awaited_once()
    assert results == [obj1, obj2]


@pytest.mark.asyncio
async def test_generic_repository_update_found(mock_session: MagicMock) -> None:
    obj = _TestModel()
    mock_session.get.return_value = obj

    repo = GenericRepository(mock_session, _TestModel)
    result = await repo.update(obj.id, name="updated")

    assert result is obj
    assert obj.name == "updated"
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_generic_repository_update_not_found(mock_session: MagicMock) -> None:
    mock_session.get.return_value = None

    repo = GenericRepository(mock_session, _TestModel)
    result = await repo.update(uuid.uuid4(), name="updated")

    assert result is None


@pytest.mark.asyncio
async def test_generic_repository_delete_found(mock_session: MagicMock) -> None:
    obj = _TestModel()
    mock_session.get.return_value = obj

    repo = GenericRepository(mock_session, _TestModel)
    result = await repo.delete(obj.id)

    assert result is True
    mock_session.delete.assert_called_once_with(obj)
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_generic_repository_delete_not_found(mock_session: MagicMock) -> None:
    mock_session.get.return_value = None

    repo = GenericRepository(mock_session, _TestModel)
    result = await repo.delete(uuid.uuid4())

    assert result is False


@pytest.mark.asyncio
async def test_tenant_scoped_create_injects_tenant(
    mock_session: MagicMock, tenant_id: uuid.UUID, with_tenant: None
) -> None:
    repo = TenantScopedRepository(mock_session, _TestModel)
    instance = await repo.create(name="scoped")

    assert instance.tenant_id == tenant_id
    mock_session.add.assert_called_once()
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_tenant_scoped_create_respects_explicit_tenant(
    mock_session: MagicMock, tenant_id: uuid.UUID
) -> None:
    """If tenant_id is explicitly passed, context tenant is not overridden."""
    set_tenant(tenant_id)
    other = uuid.UUID("33333333-3333-4333-8333-333333333333")
    repo = TenantScopedRepository(mock_session, _TestModel)
    instance = await repo.create(name="explicit", tenant_id=other)

    assert instance.tenant_id == other


@pytest.mark.asyncio
async def test_tenant_scoped_get_filters_by_tenant(
    mock_session: MagicMock, tenant_id: uuid.UUID, with_tenant: None
) -> None:
    obj = _TestModel()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = obj
    mock_session.execute.return_value = mock_result

    repo = TenantScopedRepository(mock_session, _TestModel)
    result = await repo.get(obj.id)

    assert result is obj
    call_args = mock_session.execute.call_args[0][0]
    compiled = call_args.compile(compile_kwargs={"literal_binds": True})
    assert "tenant_id =" in compiled.string
    assert "tenant_id IS NULL" not in compiled.string


@pytest.mark.asyncio
async def test_tenant_scoped_find_injects_tenant(
    mock_session: MagicMock, tenant_id: uuid.UUID, with_tenant: None
) -> None:
    obj = _TestModel(tenant_id=tenant_id)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [obj]
    mock_session.execute.return_value = mock_result

    repo = TenantScopedRepository(mock_session, _TestModel)
    results = await repo.find(name="scoped")

    assert results == [obj]


@pytest.mark.asyncio
async def test_tenant_scoped_create_without_context(
    mock_session: MagicMock,
) -> None:
    """When no tenant context is active, create should not inject tenant_id."""
    repo = TenantScopedRepository(mock_session, _TestModel)
    instance = await repo.create(name="no-tenant")

    assert getattr(instance, "tenant_id", None) is None


@pytest.mark.asyncio
async def test_tenant_scoped_get_without_context_returns_none(
    mock_session: MagicMock,
) -> None:
    """When tenant context is None, the query filters by None which returns no rows."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    repo = TenantScopedRepository(mock_session, _TestModel)
    result = await repo.get(uuid.uuid4())

    assert result is None
