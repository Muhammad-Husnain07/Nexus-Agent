"""add_compensating_operation

Revision ID: 3a2b1c0d9e8f
Revises: c7f80200ca2a
Create Date: 2026-08-02

Adds ``tool.compensating_operation`` — metadata naming the tool that undoes
a side-effectful call (saga compensation).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "3a2b1c0d9e8f"
down_revision: Union[str, None] = "c7f80200ca2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tool",
        sa.Column(
            "compensating_operation",
            sa.String(length=255),
            nullable=True,
            comment="Tool name that UNDOES this tool's side effects (saga compensation)",
        ),
    )


def downgrade() -> None:
    op.drop_column("tool", "compensating_operation")
