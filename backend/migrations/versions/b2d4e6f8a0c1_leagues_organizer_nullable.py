"""make leagues.organizer_id nullable

Revision ID: b2d4e6f8a0c1
Revises: a3f9b1c4d7e2
Create Date: 2026-06-15 00:00:00.000000

MYS-50: account hard-purge nulls the organizer of any *completed* league the
purged user organized, rather than destroying other members' history. The
column must therefore tolerate NULL. Active leagues never reach this state —
deletion is blocked while the caller organizes an active league.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b2d4e6f8a0c1"
down_revision: Union[str, Sequence[str], None] = "a3f9b1c4d7e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("leagues", "organizer_id", nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("leagues", "organizer_id", nullable=False)
