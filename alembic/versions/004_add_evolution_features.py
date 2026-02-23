"""add evolution tracking features

Revision ID: 004
Revises: 003
Create Date: 2026-02-23 10:27:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create keyword_usage table
    op.create_table('keyword_usage',
        sa.Column('keyword', sa.String(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('use_count', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('keyword')
    )
    
    # 2. Add new_results_count to search_runs
    # In SQLite, adding a column with a default is supported since 3.1.6
    with op.batch_alter_table('search_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('new_results_count', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    # 1. Remove new_results_count from search_runs
    with op.batch_alter_table('search_runs', schema=None) as batch_op:
        batch_op.drop_column('new_results_count')
    
    # 2. Drop keyword_usage table
    op.drop_table('keyword_usage')
