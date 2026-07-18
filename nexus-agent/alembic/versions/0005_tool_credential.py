"""Add tool_credential table for encrypted tool auth secrets.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_credential",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "tool_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tool.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("auth_type", sa.String(50), nullable=False),
        sa.Column("encrypted_blob", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_tool_credential_tid_id", "tool_credential", ["tenant_id", "id"]
    )
    op.create_index(
        "ix_tool_credential_tid_created",
        "tool_credential",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tool_credential_tid_created", table_name="tool_credential")
    op.drop_index("ix_tool_credential_tid_id", table_name="tool_credential")
    op.drop_table("tool_credential")
