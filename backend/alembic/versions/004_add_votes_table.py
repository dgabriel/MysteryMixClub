"""Add votes table

Revision ID: 004
Revises: 003
Create Date: 2026-01-03 21:00:00.000000

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
    # Create votes table
    op.create_table(
        'votes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('round_id', sa.Integer(), nullable=False),
        sa.Column('voter_id', sa.Integer(), nullable=False),
        sa.Column('submission_id', sa.Integer(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('voted_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['round_id'], ['rounds.id'], ),
        sa.ForeignKeyConstraint(['voter_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['submission_id'], ['submissions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_votes_id'), 'votes', ['id'], unique=False)
    # Unique constraint: one rank per voter per round
    op.create_index('ix_votes_voter_round_rank', 'votes', ['voter_id', 'round_id', 'rank'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_votes_voter_round_rank', table_name='votes')
    op.drop_index(op.f('ix_votes_id'), table_name='votes')
    op.drop_table('votes')
