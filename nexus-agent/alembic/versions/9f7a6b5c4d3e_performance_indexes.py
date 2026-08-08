"""performance_indexes

Revision ID: 9f7a6b5c4d3e
Revises: 5f5863421589
Create Date: 2026-08-02

Adds production performance indexes:
- HNSW vector indexes on memory.embedding / tool.embedding (semantic search).
  pgvector caps HNSW/IVFFlat at 2000 dimensions — the index is created only
  when the configured column dimension supports it, otherwise skipped with
  a warning (large-dim embeddings (e.g. 4096) remain searchable via exact
  scan until the deployment lowers embedding_dimensions).
- Composite scheduler index on long_running_workflow(status, next_run_at)
- Unique constraints on toolversion(tool_id, version) and registry_version(version)
"""
from __future__ import annotations

from typing import Sequence, Union

import structlog
from alembic import op

logger = structlog.get_logger("alembic.performance_indexes")

revision: str = "9f7a6b5c4d3e"
down_revision: Union[str, None] = "5f5863421589"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# pgvector hard limit for HNSW/IVFFlat index operator classes
_PGVECTOR_INDEX_MAX_DIMS = 2000


def _embedding_dims(conn, table: str) -> int | None:
    """Read the vector column dimension from the live schema."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            "SELECT atttypmod FROM pg_attribute WHERE attrelid = "
            f"'{table}'::regclass AND attname = 'embedding'"
        )
    ).fetchone()
    if row is None or row[0] is None:
        return None
    # vector(n) → atttypmod = n + 4 (header)
    return row[0] - 4


def upgrade() -> None:
    bind = op.get_bind()

    for table in ("memory", "tool"):
        dims = _embedding_dims(bind, table)
        if dims is not None and 0 < dims <= _PGVECTOR_INDEX_MAX_DIMS:
            op.execute(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_embedding_hnsw "
                f"ON {table} USING hnsw (embedding vector_cosine_ops)"
            )
            logger.info("hnsw.index_created", table=table, dims=dims)
        else:
            logger.warning(
                "hnsw.index_skipped",
                table=table,
                dims=dims,
                hint="HNSW supports up to 2000 dims; lower "
                "NEXUS_LLM__EMBEDDING_DIMENSIONS to enable indexed search",
            )

    # ── Scheduler composite index ────────────────────────────────────────
    op.create_index(
        "ix_long_running_workflow_status_next_run",
        "long_running_workflow",
        ["status", "next_run_at"],
        unique=False,
    )

    # ── Uniqueness for version history ───────────────────────────────────
    op.create_unique_constraint(
        "uq_toolversion_tool_version", "toolversion", ["tool_id", "version"]
    )
    op.create_unique_constraint(
        "uq_registry_version_version", "registry_version", ["version"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_registry_version_version", "registry_version", type_="unique")
    op.drop_constraint("uq_toolversion_tool_version", "toolversion", type_="unique")
    op.drop_index("ix_long_running_workflow_status_next_run", table_name="long_running_workflow")
    op.execute("DROP INDEX IF EXISTS ix_tool_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_memory_embedding_hnsw")
