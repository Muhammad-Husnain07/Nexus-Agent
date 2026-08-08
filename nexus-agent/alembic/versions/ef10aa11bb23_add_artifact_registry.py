"""add artifact registry table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-04 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ef10aa11bb23'
down_revision: Union[str, None] = 'ef10aa11bb22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'artifact_registry',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('capability_id', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('tool_name', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('type', sa.String(length=100), nullable=False, server_default='GenericArtifact'),
        sa.Column('schema_version', sa.String(length=50), nullable=False, server_default='1.0'),
        sa.Column('artifact_revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='created'),
        sa.Column('parent_artifact_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('execution_id', sa.String(length=100), nullable=True),
        sa.Column('data', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_artifact_registry_session_id', 'artifact_registry', ['session_id'])
    op.create_index('ix_artifact_registry_capability_id', 'artifact_registry', ['capability_id'])
    op.create_index('ix_artifact_registry_tool_name', 'artifact_registry', ['tool_name'])
    op.create_index('ix_artifact_registry_type', 'artifact_registry', ['type'])
    op.create_index('ix_artifact_registry_status', 'artifact_registry', ['status'])
    op.create_index('ix_artifact_registry_execution_id', 'artifact_registry', ['execution_id'])


def downgrade() -> None:
    op.drop_table('artifact_registry')
