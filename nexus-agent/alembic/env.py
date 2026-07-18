"""Alembic migration environment configuration with async engine support."""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from nexus.config.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import ALL models so they register on Base.metadata
import nexus.db.models  # noqa: E402, F401
from nexus.db.base import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script generation)."""
    url = get_settings().database.url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure and run migrations against a sync-style connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create extensions and run migrations using an async engine."""
    settings = get_settings()
    connectable = create_async_engine(settings.database.url)

    async with connectable.connect() as connection:
        # Create required PostgreSQL extensions before any migrations
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await connection.commit()

        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode via async engine.

    Detects whether an event loop is already running (e.g. inside
    pytest-asyncio) and uses ``run_until_complete`` to avoid nesting
    ``asyncio.run()`` calls, which raises ``RuntimeError``.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.run_until_complete(run_async_migrations())
    except RuntimeError:
        # No running loop — safe to call asyncio.run()
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
elif not os.environ.get("NEXUS_SKIP_AUTO_MIGRATE"):
    run_migrations_online()
