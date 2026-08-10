"""add session + memory ownership (user_id)

C3/P0-C tenant isolation: sessions and memories carry the owning user_id
as an arbitrary identity string (JWT sub / api-key / "anonymous" — NOT a
FK, identity providers are external). Legacy rows keep NULL (documented
open posture; production deployments backfill). Revision ID: c9d8e7f6a5b4
"""

import sqlalchemy as sa
from alembic import op

revision = "c9d8e7f6a5b4"
down_revision = "556c8a902f17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session",
        sa.Column("user_id", sa.String(128), nullable=True),
    )
    op.create_index("ix_sessions_user_id", "session", ["user_id"])
    op.add_column(
        "memory",
        sa.Column("user_id", sa.String(128), nullable=True),
    )
    op.create_index("ix_memory_user_id", "memory", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_user_id", table_name="memory")
    op.drop_column("memory", "user_id")
    op.drop_index("ix_sessions_user_id", table_name="session")
    op.drop_column("session", "user_id")
