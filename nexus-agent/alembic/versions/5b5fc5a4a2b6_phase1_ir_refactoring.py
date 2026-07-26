"""phase1_ir_refactoring — add logical_op_name/batch_strategy, move cost/latency to endpoint, drop goal_template

Revision ID: 5b5fc5a4a2b6
Revises: 2a475ec2e137
Create Date: 2026-07-26 05:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5b5fc5a4a2b6"
down_revision: Union[str, None] = "2a475ec2e137"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── CapabilityModel: add logical_op_name and batch_strategy ──
    op.add_column(
        "capability",
        sa.Column(
            "logical_op_name", sa.String(255), nullable=True, unique=True,
            comment="Logical operation name used by the Semantic Planner (e.g., 'get_weather')",
        ),
    )
    op.create_index("ix_capability_logical_op_name", "capability", ["logical_op_name"])
    op.add_column(
        "capability",
        sa.Column(
            "batch_strategy", sa.String(50), server_default="none", nullable=False,
            comment="Batch fusion strategy: 'none', 'fuse', or 'split'",
        ),
    )

    # ── ProviderModel: drop cost_per_call and sla_p99_ms (moved to EndpointModel) ──
    op.drop_column("provider", "cost_per_call")
    op.drop_column("provider", "sla_p99_ms")

    # ── EndpointModel: add cost_per_call, latency_p99_ms, supports_batch ──
    op.add_column(
        "endpoint",
        sa.Column(
            "cost_per_call", sa.Float(), server_default=sa.text("0.0"), nullable=False,
            comment="Cost per invocation in USD (moved from ProviderModel)",
        ),
    )
    op.add_column(
        "endpoint",
        sa.Column(
            "latency_p99_ms", sa.Integer(), nullable=True,
            comment="P99 latency in milliseconds (moved from ProviderModel.sla_p99_ms)",
        ),
    )
    op.add_column(
        "endpoint",
        sa.Column(
            "supports_batch", sa.Boolean(), server_default=sa.text("false"), nullable=False,
            comment="Whether this endpoint supports batch requests",
        ),
    )

    # ── Drop GoalTemplateModel and its association table ──
    op.drop_table("goal_template_capability")
    op.drop_table("goal_template")


def downgrade() -> None:
    # ── Restore goal_template tables ──
    op.create_table(
        "goal_template",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, comment="Unique template name"),
        sa.Column("trigger_action", sa.String(255), nullable=False),
        sa.Column("expansion_logic", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "goal_template_capability",
        sa.Column("goal_template_id", sa.UUID(), nullable=False),
        sa.Column("capability_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["goal_template_id"], ["goal_template.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["capability_id"], ["capability.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("goal_template_id", "capability_id"),
    )

    # ── EndpointModel: drop new columns ──
    op.drop_column("endpoint", "supports_batch")
    op.drop_column("endpoint", "latency_p99_ms")
    op.drop_column("endpoint", "cost_per_call")

    # ── ProviderModel: restore sla_p99_ms and cost_per_call ──
    op.add_column(
        "provider",
        sa.Column("sla_p99_ms", sa.Integer(), nullable=True, comment="P99 latency SLA in milliseconds"),
    )
    op.add_column(
        "provider",
        sa.Column("cost_per_call", sa.Float(), server_default=sa.text("0.0"), nullable=False),
    )

    # ── CapabilityModel: drop new columns ──
    op.drop_index("ix_capability_logical_op_name", table_name="capability")
    op.drop_column("capability", "batch_strategy")
    op.drop_column("capability", "logical_op_name")
