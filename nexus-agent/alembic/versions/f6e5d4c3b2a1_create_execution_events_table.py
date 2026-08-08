"""create_execution_events_table — codify execution_events table in Alembic

Revision ID: f6e5d4c3b2a1
Revises: a1b2c3d4e5f6
Create Date: 2026-07-27 00:00:00.000000

Replaces the previous runtime ``ensure_event_store_table()`` approach with
a proper managed migration. The ``execution_events`` table is an append-only
event log for execution event sourcing.

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f6e5d4c3b2a1"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(255), nullable=False, index=True),
        sa.Column(
            "event_type",
            sa.String(100),
            nullable=False,
            comment="Event type: task_started/task_completed/task_failed/wave_completed/execution_completed",
        ),
        sa.Column(
            "task_id",
            sa.String(100),
            nullable=True,
            comment="Task identifier if event is task-scoped",
        ),
        sa.Column("tool_name", sa.String(255), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="Event payload (result, error, timing)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("execution_events")
