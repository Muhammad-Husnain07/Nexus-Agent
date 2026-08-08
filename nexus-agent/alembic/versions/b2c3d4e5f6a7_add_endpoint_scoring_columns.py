"""add_endpoint_scoring_columns — add required_permissions, api_version, deprecated, min_tier

Revision ID: b2c3d4e5f6a7
Revises: f6e5d4c3b2a1
Create Date: 2026-07-27 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "f6e5d4c3b2a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "endpoint",
        sa.Column(
            "required_permissions",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="Permissions required to use this endpoint",
        ),
    )
    op.add_column(
        "endpoint",
        sa.Column(
            "api_version",
            sa.String(50),
            nullable=True,
            comment="API version identifier",
        ),
    )
    op.add_column(
        "endpoint",
        sa.Column(
            "deprecated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Whether this endpoint is deprecated",
        ),
    )
    op.add_column(
        "endpoint",
        sa.Column(
            "min_tier",
            sa.String(50),
            nullable=True,
            comment="Minimum user tier required",
        ),
    )


def downgrade() -> None:
    op.drop_column("endpoint", "min_tier")
    op.drop_column("endpoint", "deprecated")
    op.drop_column("endpoint", "api_version")
    op.drop_column("endpoint", "required_permissions")
