"""add_registry_models — capability, provider, endpoint, goal_template, registry_version

Revision ID: 2a475ec2e137
Revises: 001b70671b50
Create Date: 2026-07-25 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2a475ec2e137"
down_revision: Union[str, None] = "001b70671b50"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### capability table
    op.create_table(
        "capability",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, comment="Unique capability name"),
        sa.Column("description", sa.Text(), server_default="", nullable=False, comment="Human-readable description"),
        sa.Column("ontology_parent", sa.String(255), nullable=True, comment="Parent capability name for ontology hierarchy"),
        sa.Column("consumes", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False, comment="Artifact field names required as input"),
        sa.Column("produces", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False, comment="Artifact field names produced as output"),
        sa.Column("preconditions", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False, comment="Conditions that must be true before execution"),
        sa.Column("postconditions", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False, comment="Conditions that are true after execution"),
        sa.Column("contract", postgresql.JSONB(), server_default="{}", nullable=False, comment="Contract JSON — idempotency, cost model, SLA guarantees"),
        sa.Column("tags", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False, comment="Categorization tags"),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False, comment="Whether the capability is active"),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False, comment="Capability definition version"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # ### provider table
    op.create_table(
        "provider",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("capability_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, comment="Provider name"),
        sa.Column("description", sa.Text(), server_default="", nullable=False, comment="Provider description"),
        sa.Column("sla_p99_ms", sa.Integer(), nullable=True, comment="P99 latency SLA in milliseconds"),
        sa.Column("cost_per_call", sa.Float(), server_default=sa.text("0.0"), nullable=False, comment="Cost per invocation in USD"),
        sa.Column("privacy_level", sa.String(50), server_default="low", nullable=False, comment="Privacy level: low | medium | high"),
        sa.Column("reliability_score", sa.Float(), server_default=sa.text("1.0"), nullable=False, comment="EWMA reliability score (0.0–1.0)"),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=True, comment="Max requests per minute"),
        sa.Column("retry_policy", sa.String(50), server_default="default", nullable=False, comment="Retry strategy: default | aggressive | conservative"),
        sa.Column("circuit_breaker_threshold", sa.Integer(), server_default=sa.text("5"), nullable=False, comment="Consecutive failures before circuit opens"),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False, comment="Whether the provider is active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["capability_id"], ["capability.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ### endpoint table
    op.create_table(
        "endpoint",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False, comment="Endpoint URL"),
        sa.Column("http_method", sa.String(10), server_default="GET", nullable=False, comment="HTTP method"),
        sa.Column("auth_type", sa.String(50), server_default="none", nullable=False, comment="Authentication type"),
        sa.Column("region", sa.String(100), server_default="global", nullable=False, comment="Geographic region"),
        sa.Column("weight", sa.Integer(), server_default=sa.text("1"), nullable=False, comment="Load balancing weight"),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False, comment="Whether the endpoint is active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ### goal_template table
    op.create_table(
        "goal_template",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, comment="Unique template name"),
        sa.Column("trigger_action", sa.String(255), nullable=False, comment="Action that triggers this template (e.g., 'compare')"),
        sa.Column("expansion_logic", postgresql.JSONB(), server_default="{}", nullable=False, comment="Expansion rules — YAML/JSON defining goal sequences"),
        sa.Column("description", sa.Text(), server_default="", nullable=False, comment="Template description"),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False, comment="Template version"),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False, comment="Whether the template is active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # ### goal_template_capability association table
    op.create_table(
        "goal_template_capability",
        sa.Column("goal_template_id", sa.UUID(), nullable=False),
        sa.Column("capability_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["goal_template_id"], ["goal_template.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["capability_id"], ["capability.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("goal_template_id", "capability_id"),
    )

    # ### registry_version table
    op.create_table(
        "registry_version",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, comment="Monotonic version number"),
        sa.Column("checksum", sa.String(64), nullable=False, comment="SHA256 of compiled graph"),
        sa.Column("capability_count", sa.Integer(), server_default=sa.text("0"), nullable=False, comment="Number of compiled capabilities"),
        sa.Column("provider_count", sa.Integer(), server_default=sa.text("0"), nullable=False, comment="Number of compiled providers"),
        sa.Column("template_count", sa.Integer(), server_default=sa.text("0"), nullable=False, comment="Number of compiled templates"),
        sa.Column("has_cycles", sa.Boolean(), server_default=sa.text("false"), nullable=False, comment="Whether cycles were detected"),
        sa.Column("missing_producers", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False, comment="Artifact gaps detected"),
        sa.Column("compiled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("output_path", sa.String(1024), nullable=True, comment="Path to compiled JSON graph"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("registry_version")
    op.drop_table("goal_template_capability")
    op.drop_table("goal_template")
    op.drop_table("endpoint")
    op.drop_table("provider")
    op.drop_table("capability")
