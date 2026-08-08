"""add_long_running_workflow — table for long-running autonomous workflows

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-27 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "long_running_workflow",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(512), server_default="", nullable=False),
        sa.Column(
            "status", sa.String(50), server_default="running",
            nullable=False, comment="pending | running | paused | completed | failed",
        ),
        sa.Column(
            "workflow_graph", postgresql.JSONB(), nullable=True,
            comment="Snapshot of the execution graph for resume",
        ),
        sa.Column(
            "schedule_cron", sa.String(100), nullable=True,
            comment="Cron expression for recurring execution",
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_runs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "notify_on", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"),
            nullable=False, comment="Events triggering notification",
        ),
        sa.Column(
            "notification_target", sa.String(255), nullable=True,
            comment="Email, webhook URL, etc.",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("total_cost_usd", sa.Float(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("long_running_workflow")
