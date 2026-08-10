"""P2-C observability chain columns

Revision ID: c2d3e4f5a6b7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-10 01:00:00.000000

Closes the persisted join chain without log parsing:

    request_id (invocation_outcomes)
        → agent_run_id (invocation_outcomes + tool_execution +
                        completed_executions + artifact cache)
        → execution_key (tool_execution + completed_executions)
        → result/outcome

- tool_execution.execution_key: the logical operation identity (stable
  across retries; attempt dimension = retried column).
- completed_executions.agent_run_id: the run that claimed/completed the
  idempotency row.

Reversible: downgrade drops both columns.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tool_execution',
        sa.Column(
            'execution_key',
            sa.String(64),
            nullable=True,
            comment="Logical operation execution key (stable across attempts)",
        ),
    )
    op.add_column(
        'completed_executions',
        sa.Column(
            'agent_run_id',
            sa.String(64),
            nullable=True,
            comment="Run that claimed/completed the operation (P2-C)",
        ),
    )


def downgrade() -> None:
    op.drop_column('tool_execution', 'execution_key')
    op.drop_column('completed_executions', 'agent_run_id')
