"""Add Tidal OAuth fields to users table

Revision ID: 006
Revises: 005
Create Date: 2026-01-12
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add Tidal OAuth fields to users table
    op.add_column('users', sa.Column('tidal_user_id', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('tidal_session_data', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'tidal_session_data')
    op.drop_column('users', 'tidal_user_id')
