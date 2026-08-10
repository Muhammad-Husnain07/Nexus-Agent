"""P2-B reproducibility columns on invocation_outcomes

Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-08-10 00:00:00.000000

Persists the evidence to answer "exactly what produced this answer?":
identities (request_id, agent_run_id), LLM configuration (temperature,
seed), contract fingerprints (registry_fingerprint), planner telemetry
(planner_metrics, intent_coverage), prompt/architecture fingerprints
(reproducibility), and reference hashes for the logical workflow /
compiled plan (logical_intent_graph_ref, logical_plan_ref, attempts).

Reversible: downgrade drops every added column.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ADDED_COLUMNS = (
    # NOT NULL string columns carry a server_default so ALTER succeeds on
    # tables with existing rows (Postgres fills them with the default).
    ('architecture_fingerprint', sa.String(64), False, "ADR 0008 architecture manifest fingerprint", ''),
    ('request_id', sa.String(64), True, "API request correlation id (RequestIDMiddleware)", None),
    ('agent_run_id', sa.String(64), True, "Per-invocation run identity (_invocation_id)", None),
    ('temperature', sa.Float(), True, "Finalize LLM temperature used", None),
    ('seed', sa.Integer(), True, "LLM seed if configured (None for parity)", None),
    ('registry_fingerprint', sa.String(64), False, "Catalog/registry contract fingerprint (P1-B)", ''),
    ('planner_metrics', JSONB(), True, "Full plan-validator telemetry incl. per-intent coverage evidence", None),
    ('intent_coverage', JSONB(), True, "Aggregate intent-coverage summary (evidence lives in planner_metrics)", None),
    ('reproducibility', JSONB(), True, "Model + temperature + prompt versions/fingerprints + architecture fp", None),
    ('logical_intent_graph_ref', sa.String(64), False, "SHA256 reference to the logical workflow (checkpoint)", ''),
    ('logical_plan_ref', sa.String(64), False, "SHA256 reference to the compiled execution graph", ''),
    ('attempts', JSONB(), True, "Per-operation execution-key identity references", None),
)


def upgrade() -> None:
    for name, coltype, nullable, comment, server_default in _ADDED_COLUMNS:
        op.add_column(
            'invocation_outcomes',
            sa.Column(
                name,
                coltype,
                nullable=nullable,
                comment=comment,
                server_default=sa.text("''") if server_default == '' else None,
            ),
        )


def downgrade() -> None:
    for name, _coltype, _nullable, _comment, _server_default in reversed(_ADDED_COLUMNS):
        op.drop_column('invocation_outcomes', name)
