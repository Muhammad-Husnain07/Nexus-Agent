"""add_capability_hierarchy_and_templates — parent_capability_id + workflow_template

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-27 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add self-referential FK to capability for hierarchy
    op.add_column(
        "capability",
        sa.Column(
            "parent_capability_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Parent capability for ontology hierarchy (self-referential FK)",
        ),
    )
    op.create_foreign_key(
        "fk_capability_parent_capability_id_capability",
        "capability", "capability",
        ["parent_capability_id"], ["id"],
        ondelete="SET NULL",
    )

    # Create workflow_template table
    op.create_table(
        "workflow_template",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "name", sa.String(255), nullable=False,
            comment="Unique template name",
        ),
        sa.Column(
            "trigger_intent_pattern", sa.String(255), nullable=False,
            comment="Keyword/intent pattern to match",
        ),
        sa.Column(
            "capability_chain",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="Ordered list of capability steps",
        ),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_nodes", sa.Integer(), server_default=sa.text("10"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("workflow_template")
    op.drop_constraint(
        "fk_capability_parent_capability_id_capability",
        "capability", type_="foreignkey",
    )
    op.drop_column("capability", "parent_capability_id")
