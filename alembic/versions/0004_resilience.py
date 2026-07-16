"""Add dead_letter_execution table and resilience-related columns.

Creates the ``dead_letter_execution`` table for the dead letter queue,
and adds ``idempotent`` and ``dead_letter`` columns to existing tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── dead_letter_execution ──────────────────────────────────────────────
    op.create_table(
        "dead_letter_execution",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("tool_id", UUID(as_uuid=True), nullable=True),
        sa.Column("input_payload", JSONB, default=dict),
        sa.Column("error_message", sa.Text, default=""),
        sa.Column("error_code", sa.String(100), default="UNKNOWN"),
        sa.Column("retry_count", sa.Integer, default=0),
        sa.Column("status", sa.String(50), default="pending"),
        sa.Column("original_timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_retry_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_dlq_tid_created", "dead_letter_execution", ["tenant_id", "created_at"])
    op.create_index("ix_dlq_tool_name", "dead_letter_execution", ["tool_name"])

    # ── Add columns to tool_execution ──────────────────────────────────────
    op.add_column("tool_execution", sa.Column("dead_letter", sa.Boolean(), server_default=sa.text("false")))
    op.add_column("tool_execution", sa.Column("dead_letter_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tool_execution", sa.Column("idempotency_key", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("tool_execution", "idempotency_key")
    op.drop_column("tool_execution", "dead_letter_at")
    op.drop_column("tool_execution", "dead_letter")
    op.drop_index("ix_dlq_tool_name", table_name="dead_letter_execution")
    op.drop_index("ix_dlq_tid_created", table_name="dead_letter_execution")
    op.drop_table("dead_letter_execution")
