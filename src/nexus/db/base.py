"""SQLAlchemy declarative base, async engine factory, session, and tenant mixin."""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import ForeignKey, Index, MetaData
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from nexus.config.settings import get_settings

convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all database models with naming convention."""

    metadata = MetaData(naming_convention=convention)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return cls.__name__.lower()

    id: Any = None  # redefined in every subclass
    tenant_id: Any = None  # redefined via TenantMixin


def tenant_table_args(
    name: str,
    *extra_args: object,
) -> tuple[object, ...]:
    """Build __table_args__ tuple with standard tenant composite indexes.

    Every tenant-scoped table should include (tenant_id, id) and
    (tenant_id, created_at) composite indexes for efficient multi-tenant
    querying.
    """
    return (
        Index(f"ix_{name}_tid_id", "tenant_id", "id"),
        Index(f"ix_{name}_tid_created", "tenant_id", "created_at"),
    ) + extra_args


class TenantMixin:
    """Mixin that adds tenant_id foreign key and created_at index helpers.

    Every tenant-scoped table gets:
      - tenant_id UUID FK → tenant.id
    Models should add their own indexes via __table_args__.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the lazily-initialized async engine."""
    global _engine  # noqa: PLW0603
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database.url,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
            pool_pre_ping=True,
            echo=settings.database.echo_sql,
            connect_args={
                "command_timeout": settings.database.statement_timeout_ms / 1000,
            },
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the lazily-initialized session factory."""
    global _session_factory  # noqa: PLW0603
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def dispose_engine() -> None:
    """Dispose the engine's connection pool (call on shutdown)."""
    global _engine, _session_factory  # noqa: PLW0603
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an AsyncSession."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async_session: async_sessionmaker[AsyncSession] = None  # type: ignore[assignment]


def _get_async_session() -> async_sessionmaker[AsyncSession]:
    """Lazy accessor for the session factory (backward compat)."""
    return get_session_factory()


class _AsyncSessionProxy:
    """Proxy that lazily initializes the session factory on first call."""

    def __call__(self, **kwargs: Any) -> Any:
        return get_session_factory()(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(get_session_factory(), name)


async_session = _AsyncSessionProxy()  # type: ignore[assignment]
