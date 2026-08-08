"""add_missing_capability_columns — intent_profiles, input_policy, output_contract

These columns were defined in the ORM model but never created by any
Alembic migration in the current chain. They were previously added by
an ad-hoc manual_001 migration that existed in an older copy of the
codebase but was not part of the formal migration chain.

Revision ID: f0e1d2c3b4a5
Revises: f6a7b8c9d0e1
Create Date: 2026-07-27 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f0e1d2c3b4a5"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "capability",
        sa.Column(
            "intent_profiles",
            postgresql.JSONB(),
            nullable=True,
            default=dict,
            comment="Semantic intent to API param mappings",
        ),
    )
    op.add_column(
        "capability",
        sa.Column(
            "input_policy",
            postgresql.JSONB(),
            nullable=True,
            default=dict,
            comment="Default params and computed field paths",
        ),
    )
    op.add_column(
        "capability",
        sa.Column(
            "output_contract",
            postgresql.JSONB(),
            nullable=True,
            default=dict,
            comment="Expected response shape for validation",
        ),
    )


def downgrade() -> None:
    op.drop_column("capability", "output_contract")
    op.drop_column("capability", "input_policy")
    op.drop_column("capability", "intent_profiles")
