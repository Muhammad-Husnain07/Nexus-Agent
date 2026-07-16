"""SQLAlchemy declarative base, async engine factory, session, and tenant mixin."""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import ForeignKey, Index, MetaData
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
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


def create_async_engine_from_settings() -> Any:
    """Create an AsyncEngine from Settings."""
    settings = get_settings()
    return create_async_engine(
        settings.database.url,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
        pool_pre_ping=True,
        echo=settings.database.echo_sql,
        connect_args={
            "statement_timeout": settings.database.statement_timeout_ms,
        },
    )


engine = create_async_engine_from_settings()
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an AsyncSession."""
    async with async_session() as session:
        yield session
