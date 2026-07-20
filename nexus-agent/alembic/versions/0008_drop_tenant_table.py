"""Drop tenant table and all FK constraints referencing it."""
from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: ClassVar[list[str] | None] = None
depends_on: ClassVar[list[str] | None] = None


def upgrade() -> None:
    # Drop FK constraints — use raw SQL to avoid issues with non-existent tables
    conn = op.get_bind()
    conn.execute(sa.text("""
        DO $$DECLARE
            r RECORD;
        BEGIN
            FOR r IN (
                SELECT conname, conrelid::regclass AS tbl
                FROM pg_constraint
                WHERE confrelid = 'tenant'::regclass
                  AND contype = 'f'
            ) LOOP
                EXECUTE 'ALTER TABLE ' || r.tbl || ' DROP CONSTRAINT ' || r.conname;
            END LOOP;
        END$$;
    """))
    # Drop tables with no remaining model
    for tbl in ["audit_log", "api_key", '"user"', "embed_config", "tool_credential"]:
        conn.execute(sa.text(f"DROP TABLE IF EXISTS {tbl} CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS tenant CASCADE"))


def downgrade() -> None:
    op.create_table(
        "tenant",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("settings", sa.JSONB(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )
