"""add tool_type mcp tenant idempotent columns

Revision ID: 78c888e39c34
Revises: 3a2b1c0d9e8f
Create Date: 2026-08-02 23:24:48.011754

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '78c888e39c34'
down_revision: Union[str, None] = '3a2b1c0d9e8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add NOT NULL columns with a temporary server default so existing rows
    # are backfilled, then drop the default (the ORM supplies values).
    op.add_column('tool', sa.Column('tool_type', sa.String(length=20), nullable=False,
                                    server_default='http_api',
                                    comment='Tool type: http_api | mcp'))
    op.add_column('tool', sa.Column('mcp_server_url', sa.String(length=2048), nullable=True,
                                    comment='MCP server URL (required for mcp)'))
    op.add_column('tool', sa.Column('tenant_public', sa.Boolean(), nullable=False,
                                    server_default=sa.false(),
                                    comment='Whether the tool is visible to all tenants'))
    op.add_column('tool', sa.Column('idempotent', sa.Boolean(), nullable=False,
                                    server_default=sa.false(),
                                    comment='Whether the tool supports idempotent execution (safe to retry)'))
    op.alter_column('tool', 'tool_type', server_default=None)
    op.alter_column('tool', 'tenant_public', server_default=None)
    op.alter_column('tool', 'idempotent', server_default=None)


def downgrade() -> None:
    op.drop_column('tool', 'idempotent')
    op.drop_column('tool', 'tenant_public')
    op.drop_column('tool', 'mcp_server_url')
    op.drop_column('tool', 'tool_type')
