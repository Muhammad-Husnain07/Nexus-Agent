"""add_requires_approval_column — add requires_approval to tool table

Revision ID: a1b2c3d4e5f6
Revises: 5b5fc5a4a2b6
Create Date: 2026-07-27 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "5b5fc5a4a2b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tool",
        sa.Column(
            "requires_approval",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="If True, tool execution requires explicit human approval",
        ),
    )


def downgrade() -> None:
    op.drop_column("tool", "requires_approval")
