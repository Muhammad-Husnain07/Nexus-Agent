"""Smoke test: runs migration, inserts Tenant+Tool, verifies tenant isolation.

Usage:
    # Start PG first:
    docker compose -f docker/docker-compose.yml up -d postgres

    # Run smoke test:
    uv run python scripts/smoke_test_db.py

Requires a running PG 16 + pgvector at NEXUS_DATABASE__URL (default:
postgresql+asyncpg://nexus:nexus@localhost:5432/nexus).
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from nexus.config.settings import get_settings
from nexus.db.base import async_session as session_factory
from nexus.db.context import set_tenant
from nexus.db.models.tenant import Tenant
from nexus.db.models.tool import Tool
from nexus.db.repositories import TenantScopedRepository

_STEP = 0


class SmokeError(Exception):
    pass


def step(msg: str) -> None:
    global _STEP  # noqa: PLW0603
    _STEP += 1
    print(f"\n[{_STEP}] {msg}")


async def check_extensions(conn: object) -> None:
    for ext in ("vector", "uuid-ossp"):
        row = await conn.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = :ext)"),
            {"ext": ext},
        )
        if row.scalar() is not True:
            raise SmokeError(f"{ext} extension not installed")
    print("  ✓ vector + uuid-ossp extensions present")


async def check_tables(conn: object) -> None:
    expected = {
        "tenant",
        "user",
        "api_key",
        "session",
        "message",
        "tool",
        "tool_execution",
        "agent_run",
        "approval",
        "memory",
        "audit_log",
    }
    rows = await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    actual = {r[0] for r in rows.fetchall()}
    missing = expected - actual
    if missing:
        raise SmokeError(f"Missing tables: {missing}")
    print(f"  ✓ All {len(expected)} tables present")


async def check_indexes(conn: object) -> None:
    expected_idx = {
        "ix_user_tid_id",
        "ix_user_tid_created",
        "ix_api_key_tid_id",
        "ix_api_key_tid_created",
        "ix_session_tid_id",
        "ix_session_tid_created",
        "ix_message_tid_id",
        "ix_message_tid_created",
        "ix_tool_tid_id",
        "ix_tool_tid_created",
        "ix_tool_execution_tid_id",
        "ix_tool_execution_tid_created",
        "ix_agent_run_tid_id",
        "ix_agent_run_tid_created",
        "ix_approval_tid_id",
        "ix_approval_tid_created",
        "ix_memory_tid_id",
        "ix_memory_tid_created",
        "ix_audit_log_tid_id",
        "ix_audit_log_tid_created",
    }
    rows = await conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))
    actual_idx = {r[0] for r in rows.fetchall()}
    missing_idx = expected_idx - actual_idx
    if missing_idx:
        raise SmokeError(f"Missing indexes: {missing_idx}")
    print("  ✓ Composite indexes present")


async def check_trigger(conn: object) -> None:
    row = await conn.execute(
        text("""
            SELECT EXISTS(
                SELECT 1 FROM pg_trigger
                WHERE tgname = 'trg_session_updated_at'
            )
        """)
    )
    if row.scalar() is not True:
        raise SmokeError("updated_at trigger missing")
    print("  ✓ updated_at trigger installed")


async def repo_smoke_test() -> None:
    step("Testing tenant creation and isolation via repositories")
    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()

    async with session_factory() as session:
        repo = TenantScopedRepository(session, Tenant)
        set_tenant(tenant_a_id)
        await repo.create(id=tenant_a_id, name="Tenant A", slug="tenant-a")
        set_tenant(tenant_b_id)
        await repo.create(id=tenant_b_id, name="Tenant B", slug="tenant-b")
        await session.commit()
        print("  ✓ Created two tenants")

        tool_repo = TenantScopedRepository(session, Tool)
        set_tenant(tenant_a_id)
        await tool_repo.create(
            name="tenant-a-tool",
            description="Tool for Tenant A",
            tenant_id=tenant_a_id,
        )
        set_tenant(tenant_b_id)
        await tool_repo.create(
            name="tenant-b-tool",
            description="Tool for Tenant B",
            tenant_id=tenant_b_id,
        )
        await session.commit()
        print("  ✓ Created tools in both tenants")

        set_tenant(tenant_a_id)
        a_tools = await tool_repo.find()
        if len(a_tools) != 1 or a_tools[0].name != "tenant-a-tool":
            raise SmokeError("Tenant A isolation failed")
        print(f"  ✓ Tenant A sees {len(a_tools)} tool(s) only")

        set_tenant(tenant_b_id)
        b_tools = await tool_repo.find()
        if len(b_tools) != 1 or b_tools[0].name != "tenant-b-tool":
            raise SmokeError("Tenant B isolation failed")
        print(f"  ✓ Tenant B sees {len(b_tools)} tool(s) only")


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database.url, isolation_level="AUTOCOMMIT")

    async with engine.connect() as conn:
        step("Checking pgvector + uuid-ossp extensions")
        await check_extensions(conn)

        step("Verifying all tables exist")
        await check_tables(conn)

        step("Verifying composite indexes")
        await check_indexes(conn)

        step("Verifying updated_at trigger")
        await check_trigger(conn)

    await engine.dispose()
    await repo_smoke_test()

    print(f"\n{'=' * 50}")
    print("  ALL SMOKE TESTS PASSED")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())
