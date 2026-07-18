"""Add rate_limit_per_minute column to tool table.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"


def upgrade() -> None:
    op.add_column(
        "tool",
        sa.Column(
            "rate_limit_per_minute",
            sa.Integer(),
            nullable=True,
            comment="Max requests per minute (null = unlimited)",
        ),
    )


def downgrade() -> None:
    op.drop_column("tool", "rate_limit_per_minute")
