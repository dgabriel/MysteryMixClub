"""rounds.theme nullable

Revision ID: d8b3f0c2e5a7
Revises: c7a2e4f1b9d3
Create Date: 2026-06-20 00:00:00.000000

MYS-62: rounds are auto-generated at league creation with no theme yet; the
organizer fills the theme in while the round is still pending. This drops the
NOT NULL constraint on rounds.theme.

The downgrade re-imposes NOT NULL, but existing null themes would violate it, so
it first backfills any nulls with a deterministic placeholder ('Round N') before
re-adding the constraint.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d8b3f0c2e5a7"
down_revision: Union[str, Sequence[str], None] = "c7a2e4f1b9d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("rounds", "theme", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Backfill any nulls before restoring NOT NULL, or the constraint would fail.
    op.execute("UPDATE rounds SET theme = 'Round ' || round_number WHERE theme IS NULL")
    op.alter_column("rounds", "theme", existing_type=sa.String(), nullable=False)
