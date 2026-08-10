"""add completed_executions — durable idempotency ledger (D1/P0-D, I5)

Atomic claim + lease on (session_id, execution_key); completed results
are replayed, never re-executed. Revision ID: d0e1f2a3b4c5
"""

import sqlalchemy as sa
from alembic import op

revision = "d0e1f2a3b4c5"
down_revision = "c9d8e7f6a5b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "completed_executions",
        sa.Column("session_id", sa.String(64), primary_key=True),
        sa.Column("execution_key", sa.String(64), primary_key=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("arch_fp", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("completed_executions")
