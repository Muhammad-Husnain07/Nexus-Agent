"""Add LangGraph checkpoint tables for persistent agent state.

Creates the tables required by ``PostgresSaver`` (``checkpoints``,
``checkpoint_blobs``, ``checkpoint_writes``, ``checkpoint_migrations``)
as well as the ``writes`` table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── checkpoints ──────────────────────────────────────────────────────
    op.create_table(
        "checkpoints",
        sa.Column("thread_id", sa.String(255), primary_key=True),
        sa.Column("checkpoint_ns", sa.String(255), primary_key=True, server_default=""),
        sa.Column("checkpoint_id", sa.String(255), primary_key=True),
        sa.Column("parent_checkpoint_id", sa.String(255), nullable=True),
        sa.Column("type", sa.String(50), nullable=True),
        sa.Column("checkpoint", sa.LargeBinary(), nullable=True),
        sa.Column("metadata_", sa.JSON(), nullable=True),
        sa.Column("channel_values", sa.JSON(), nullable=True),
        sa.Column("channel_versions", sa.JSON(), nullable=True),
        sa.Column("versions_seen", sa.JSON(), nullable=True),
        sa.Column("ts", sa.DateTime(), server_default=sa.text("now()")),
    )

    # ── checkpoint_blobs ─────────────────────────────────────────────────
    op.create_table(
        "checkpoint_blobs",
        sa.Column("thread_id", sa.String(255), primary_key=True),
        sa.Column("checkpoint_ns", sa.String(255), primary_key=True, server_default=""),
        sa.Column("channel", sa.String(255), primary_key=True),
        sa.Column("version", sa.String(255), primary_key=True),
        sa.Column("type", sa.String(50), nullable=True),
        sa.Column("blob", sa.LargeBinary(), nullable=True),
    )

    # ── checkpoint_writes ────────────────────────────────────────────────
    op.create_table(
        "checkpoint_writes",
        sa.Column("thread_id", sa.String(255), primary_key=True),
        sa.Column("checkpoint_ns", sa.String(255), primary_key=True, server_default=""),
        sa.Column("checkpoint_id", sa.String(255), primary_key=True),
        sa.Column("task_id", sa.String(255), primary_key=True),
        sa.Column("idx", sa.Integer(), primary_key=True),
        sa.Column("channel", sa.String(255)),
        sa.Column("type", sa.String(50), nullable=True),
        sa.Column("blob", sa.LargeBinary(), nullable=True),
    )

    # ── checkpoint_migrations ────────────────────────────────────────────
    op.create_table(
        "checkpoint_migrations",
        sa.Column("v", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    # ── writes (for Store if needed) ─────────────────────────────────────
    op.create_table(
        "writes",
        sa.Column("namespace", sa.String(255), primary_key=True),
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    # Indexes
    op.create_index("ix_checkpoints_thread_id", "checkpoints", ["thread_id"])
    op.create_index("ix_checkpoint_writes_thread_id", "checkpoint_writes", ["thread_id"])


def downgrade() -> None:
    op.drop_table("writes")
    op.drop_table("checkpoint_migrations")
    op.drop_table("checkpoint_writes")
    op.drop_table("checkpoint_blobs")
    op.drop_table("checkpoints")
