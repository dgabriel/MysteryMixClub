"""Create rounds and submissions tables with new flow

Revision ID: 003
Revises: 002
Create Date: 2026-01-03 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create rounds table with new flow
    op.create_table(
        'rounds',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('league_id', sa.Integer(), nullable=False),
        sa.Column('theme', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.Enum('pending', 'active', 'completed', name='roundstatus'), nullable=False, server_default='pending'),

        # Timestamps for round progression (calculated when round starts)
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('submission_deadline', sa.DateTime(timezone=True), nullable=True),
        sa.Column('voting_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('voting_deadline', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['league_id'], ['leagues.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_rounds_id'), 'rounds', ['id'], unique=False)
    op.create_index(op.f('ix_rounds_status'), 'rounds', ['status'], unique=False)
    op.create_index(op.f('ix_rounds_order'), 'rounds', ['league_id', 'order'], unique=False)

    # Create submissions table
    op.create_table(
        'submissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('round_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('song_title', sa.String(length=200), nullable=False),
        sa.Column('artist_name', sa.String(length=200), nullable=False),
        sa.Column('album_name', sa.String(length=200), nullable=True),
        sa.Column('songlink_url', sa.String(length=500), nullable=False),
        sa.Column('spotify_url', sa.String(length=500), nullable=True),
        sa.Column('apple_music_url', sa.String(length=500), nullable=True),
        sa.Column('youtube_url', sa.String(length=500), nullable=True),
        sa.Column('artwork_url', sa.String(length=500), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['round_id'], ['rounds.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_submissions_id'), 'submissions', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_submissions_id'), table_name='submissions')
    op.drop_table('submissions')
    op.drop_index(op.f('ix_rounds_order'), table_name='rounds')
    op.drop_index(op.f('ix_rounds_status'), table_name='rounds')
    op.drop_index(op.f('ix_rounds_id'), table_name='rounds')
    op.drop_table('rounds')
