"""Initial schema: all tables, indexes, extensions, and updated_at trigger.

Revision ID: 0001
Revises: None
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ── Extensions ──────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ── Tenant ──────────────────────────────────────────────────────────────
    op.create_table(
        "tenant",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False, unique=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column("settings", sa.JSON, nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'archived')",
            name="ck_tenant_status",
        ),
        {"comment": "Organizational tenants in the multi-tenant system"},
    )

    # ── User ────────────────────────────────────────────────────────────────
    op.create_table(
        "user",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("role", sa.String(50), nullable=False, server_default="member"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
        sa.UniqueConstraint("tenant_id", "external_id", name="uq_user_tenant_external_id"),
    )
    op.create_index("ix_user_tid_id", "user", ["tenant_id", "id"])
    op.create_index("ix_user_tid_created", "user", ["tenant_id", "created_at"])

    # ── ApiKey ──────────────────────────────────────────────────────────────
    op.create_table(
        "api_key",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("scopes", sa.ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("tenant_id", "key_hash", name="uq_apikey_tenant_hash"),
    )
    op.create_index("ix_api_key_tid_id", "api_key", ["tenant_id", "id"])
    op.create_index("ix_api_key_tid_created", "api_key", ["tenant_id", "created_at"])

    # ── Session ─────────────────────────────────────────────────────────────
    op.create_table(
        "session",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(512), nullable=False, server_default="New Session"),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column("metadata_", sa.JSON, nullable=True, server_default="{}"),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_session_status",
        ),
    )
    op.create_index("ix_session_tid_id", "session", ["tenant_id", "id"])
    op.create_index("ix_session_tid_created", "session", ["tenant_id", "created_at"])

    # ── Message ─────────────────────────────────────────────────────────────
    op.create_table(
        "message",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "session_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("content", sa.JSON, nullable=True, server_default="{}"),
        sa.Column("tool_calls", sa.JSON, nullable=True),
        sa.Column(
            "parent_message_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("message.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'tool', 'system')",
            name="ck_message_role",
        ),
    )
    op.create_index("ix_message_tid_id", "message", ["tenant_id", "id"])
    op.create_index("ix_message_tid_created", "message", ["tenant_id", "created_at"])

    # ── Tool ────────────────────────────────────────────────────────────────
    op.create_table(
        "tool",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("purpose", sa.Text, nullable=False, server_default=""),
        sa.Column("endpoint_url", sa.String(2048), nullable=False, server_default=""),
        sa.Column("http_method", sa.String(10), nullable=False, server_default="GET"),
        sa.Column("auth_type", sa.String(50), nullable=False, server_default="none"),
        sa.Column("auth_ref", sa.String(255), nullable=False, server_default=""),
        sa.Column("input_schema", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("output_schema", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("validation_rules", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("examples", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("tags", sa.ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("category", sa.String(255), nullable=False, server_default="general"),
        sa.Column(
            "requires_approval",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "risk_level",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'low'"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("embedding", VECTOR(1536), nullable=True, comment="Semantic embedding"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tool_tenant_name"),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="ck_tool_risk_level",
        ),
        sa.CheckConstraint(
            "http_method IN ('GET', 'POST', 'PUT', 'DELETE', 'PATCH')",
            name="ck_tool_http_method",
        ),
    )
    op.create_index("ix_tool_tid_id", "tool", ["tenant_id", "id"])
    op.create_index("ix_tool_tid_created", "tool", ["tenant_id", "created_at"])

    # ── AgentRun ────────────────────────────────────────────────────────────
    op.create_table(
        "agent_run",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "session_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("graph_state", sa.JSON, nullable=True),
        sa.Column("plan", sa.JSON, nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("checkpoint_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'interrupted', 'cancelled')",
            name="ck_agent_run_status",
        ),
    )
    op.create_index("ix_agent_run_tid_id", "agent_run", ["tenant_id", "id"])
    op.create_index("ix_agent_run_tid_created", "agent_run", ["tenant_id", "created_at"])

    # ── ToolExecution (depends on tool, session, agent_run) ─────────────────
    op.create_table(
        "tool_execution",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "tool_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tool.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_run_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("agent_run.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("response_payload", sa.JSON, nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'success'"),
        ),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "retried",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "status IN ('success', 'error', 'timeout', 'interrupted')",
            name="ck_tool_execution_status",
        ),
    )
    op.create_index("ix_tool_execution_tid_id", "tool_execution", ["tenant_id", "id"])
    op.create_index(
        "ix_tool_execution_tid_created",
        "tool_execution",
        ["tenant_id", "created_at"],
    )

    # ── Approval (depends on agent_run, user) ──────────────────────────────
    op.create_table(
        "approval",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "agent_run_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("agent_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_call", sa.JSON, nullable=False, server_default="{}"),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "reviewer_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision_payload", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'edited')",
            name="ck_approval_status",
        ),
    )
    op.create_index("ix_approval_tid_id", "approval", ["tenant_id", "id"])
    op.create_index("ix_approval_tid_created", "approval", ["tenant_id", "created_at"])

    # ── Memory ──────────────────────────────────────────────────────────────
    op.create_table(
        "memory",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "session_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("session.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", VECTOR(1536), nullable=True, comment="Semantic embedding"),
        sa.Column("metadata_", sa.JSON, nullable=True, server_default="{}"),
        sa.Column("importance", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "kind IN ('episodic', 'semantic', 'procedural', 'preference')",
            name="ck_memory_kind",
        ),
    )
    op.create_index("ix_memory_tid_id", "memory", ["tenant_id", "id"])
    op.create_index("ix_memory_tid_created", "memory", ["tenant_id", "created_at"])

    # ── AuditLog ────────────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("actor_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("resource_type", sa.String(255), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("ip", sa.String(45), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_audit_log_tid_id", "audit_log", ["tenant_id", "id"])
    op.create_index("ix_audit_log_tid_created", "audit_log", ["tenant_id", "created_at"])

    # ── Vector indexes ──────────────────────────────────────────────────────
    op.execute(
        "CREATE INDEX ix_tool_embedding ON tool "
        "USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX ix_memory_embedding ON memory "
        "USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )

    # ── Updated-at trigger function ─────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Apply trigger to tables with updated_at columns
    for table in ("session", "tool"):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    """Reverse the migration — drop all tables and extensions."""
    # Drop triggers
    for table in ("session", "tool"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")

    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column()")

    # Drop tables in reverse dependency order
    op.drop_table("audit_log")
    op.drop_table("memory")
    op.drop_table("approval")
    op.drop_table("tool_execution")
    op.drop_table("agent_run")
    op.drop_table("tool")
    op.drop_table("message")
    op.drop_table("session")
    op.drop_table("api_key")
    op.drop_table("user")
    op.drop_table("tenant")

    # Drop extensions (only if we created them — skip in downgrade)
    # op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
    # op.execute("DROP EXTENSION IF EXISTS vector")
