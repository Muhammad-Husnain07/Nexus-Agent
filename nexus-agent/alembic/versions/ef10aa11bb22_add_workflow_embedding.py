"""add workflow embedding column

Revision ID: a1b2c3d4e5f6
Revises: f488eaa7a36f
Create Date: 2026-08-04 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR

# revision identifiers, used by Alembic.
revision: str = 'ef10aa11bb22'
down_revision: Union[str, None] = 'f488eaa7a36f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'workflow_definition',
        sa.Column(
            'embedding',
            VECTOR(4096),
            nullable=True,
            comment="Semantic embedding for hybrid workflow matching",
        ),
    )


def downgrade() -> None:
    op.drop_column('workflow_definition', 'embedding')
