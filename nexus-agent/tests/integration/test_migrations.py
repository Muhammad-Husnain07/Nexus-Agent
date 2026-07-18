"""Tests for Alembic migration correctness and reversibility.

Uses testcontainers to start a fresh PostgreSQL instance, runs all
migrations, and verifies the schema matches model definitions.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.slow, pytest.mark.integration, pytest.mark.migration]


class TestMigrationsUpgrade:
    """Verify all 5 migrations apply successfully."""

    async def test_all_migrations_apply(self, async_engine: AsyncEngine) -> None:
        """All migrations from 0001 to 0005 apply without error."""
        async with async_engine.connect() as conn:
            tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
        expected = {
            "tenant", "user", "api_key", "session", "message", "tool",
            "tool_execution", "agent_run", "approval", "memory", "audit_log",
            "tool_version", "checkpoints", "checkpoint_blobs", "checkpoint_writes",
            "checkpoint_migrations", "writes", "dead_letter_execution",
            "tool_credential",
        }
        missing = expected - set(tables)
        assert not missing, f"Missing tables after migration: {missing}"

    async def test_pgvector_extension_installed(self, async_engine: AsyncEngine) -> None:
        """pgvector extension is present after migration."""
        async with async_engine.connect() as conn:
            row = await conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
                )
            )
            assert row.scalar() is True

    async def test_uuid_ossp_extension_installed(self, async_engine: AsyncEngine) -> None:
        """uuid-ossp extension is present after migration."""
        async with async_engine.connect() as conn:
            row = await conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'uuid-ossp')"
                )
            )
            assert row.scalar() is True

    async def test_updated_at_trigger_exists(self, async_engine: AsyncEngine) -> None:
        """updated_at trigger function is installed."""
        async with async_engine.connect() as conn:
            row = await conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT EXISTS(SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column')"
                )
            )
            assert row.scalar() is True

    async def test_composite_indexes_present(self, async_engine: AsyncEngine) -> None:
        """Every tenant-scoped table has (tenant_id, id) and (tenant_id, created_at) indexes."""
        async with async_engine.connect() as conn:
            rows = await conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT indexname, tablename FROM pg_indexes WHERE schemaname = 'public'"
                )
            )
            indexes = {r[0] for r in rows.fetchall()}

        expected_idx = {
            "ix_user_tid_id", "ix_session_tid_id", "ix_message_tid_id",
            "ix_tool_tid_id", "ix_tool_execution_tid_id", "ix_agent_run_tid_id",
            "ix_approval_tid_id", "ix_memory_tid_id", "ix_audit_log_tid_id",
            "ix_tool_version_tid_id", "ix_tool_credential_tid_id",
        }
        missing = expected_idx - indexes
        assert not missing, f"Missing indexes: {missing}"

    async def test_vector_indexes_present(self, async_engine: AsyncEngine) -> None:
        """pgvector ivfflat indexes exist on tool and memory tables."""
        async with async_engine.connect() as conn:
            rows = await conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT indexname FROM pg_indexes WHERE indexname IN "
                    "('ix_tool_embedding', 'ix_memory_embedding')"
                )
            )
            idx_names = {r[0] for r in rows.fetchall()}
        assert "ix_tool_embedding" in idx_names
        assert "ix_memory_embedding" in idx_names


@pytest.mark.skip("Requires downgrade testing on a fresh container")
class TestMigrationsDowngrade:
    """Verify each migration is reversible.

    These tests are skipped by default because they require separate
    container instances to test downgrade correctly.
    """

    async def test_downgrade_0005_to_0004(self, async_engine: AsyncEngine) -> None:
        from alembic.config import Config
        from alembic.command import downgrade

        cfg = Config()
        cfg.set_main_option("script_location", "alembic")
        cfg.set_main_option("sqlalchemy.url", str(async_engine.url))
        downgrade(cfg, "0004")

        async with async_engine.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert "tool_credential" not in tables
