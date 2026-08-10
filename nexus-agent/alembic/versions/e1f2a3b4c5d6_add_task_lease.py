"""add task lease columns (D5/P0-D — worker claim/lease semantics)

worker_id + lease_expires_at give the DB task row an atomic lease: a
worker holds the lease while executing; an expired lease is safely
reclaimable after a crash. Revision ID: e1f2a3b4c5d6
"""

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task", sa.Column("worker_id", sa.String(64), nullable=True))
    op.add_column(
        "task",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_task_lease", "task", ["worker_id", "lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_task_lease", table_name="task")
    op.drop_column("task", "lease_expires_at")
    op.drop_column("task", "worker_id")
