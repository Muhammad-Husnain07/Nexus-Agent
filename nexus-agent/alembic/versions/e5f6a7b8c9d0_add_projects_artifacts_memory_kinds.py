"""add_projects_artifacts_memory_kinds — project, artifact, session.project_id

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-27 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Project table ───────────────────────────────────────────────
    op.create_table(
        "project",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(512), nullable=False, comment="Project name"),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "status", sa.String(50), server_default="active",
            nullable=False, comment="active | archived | completed",
        ),
        sa.Column(
            "owner_id", postgresql.UUID(as_uuid=True),
            nullable=True, comment="Project owner (user ID)",
        ),
        sa.Column(
            "metadata_", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"),
            nullable=True, comment="Arbitrary project metadata",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_project_owner_id_user", "project", "user",
        ["owner_id"], ["id"], ondelete="SET NULL",
    )

    # ── Artifact table ──────────────────────────────────────────────
    op.create_table(
        "artifact",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind", sa.String(50), nullable=False,
            comment="dashboard | report | dataset | config | prompt",
        ),
        sa.Column("name", sa.String(512), server_default="", nullable=False),
        sa.Column(
            "parent_artifact_id", postgresql.UUID(as_uuid=True),
            nullable=True, comment="Parent artifact for branching",
        ),
        sa.Column(
            "content", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"),
            nullable=False, comment="Artifact content",
        ),
        sa.Column(
            "content_hash", sa.String(64), server_default="",
            nullable=False, comment="SHA256 of content",
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True),
            nullable=True, comment="Originating session ID",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_artifact_id"], ["artifact.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="SET NULL"),
    )

    # ── Add project_id to session ───────────────────────────────────
    op.add_column(
        "session",
        sa.Column(
            "project_id", postgresql.UUID(as_uuid=True),
            nullable=True, comment="Optional parent project ID",
        ),
    )
    op.create_foreign_key(
        "fk_session_project_id_project",
        "session", "project",
        ["project_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_session_project_id_project", "session", type_="foreignkey")
    op.drop_column("session", "project_id")
    op.drop_table("artifact")
    op.drop_constraint("fk_project_owner_id_user", "project", type_="foreignkey")
    op.drop_table("project")
