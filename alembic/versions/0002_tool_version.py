"""Add tool_version table for tool definition version history.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-16
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "tool_version",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "tool_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tool.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("snapshot", sa.JSON, nullable=False),
        sa.Column("changed_by", sa.String(255), nullable=True),
        sa.Column("change_comment", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_tool_version_tid_id", "tool_version", ["tenant_id", "id"])
    op.create_index("ix_tool_version_tid_created", "tool_version", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_table("tool_version")
