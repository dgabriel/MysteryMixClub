"""songs per submission

Revision ID: b7d4e2f09a13
Revises: d5f3a9c14b27
Create Date: 2026-06-27 00:00:00.000000

MYS-116: a player may submit more than one song per round.

* leagues.songs_per_submission — admin-set per-league cap, chosen at setup and
  applied to every round (server_default 1 = today's one-song behavior).
* drop submissions.uq_submissions_round_user — (round_id, user_id) is no longer
  unique now that a player can hold several songs in a round. The per-column
  indexes on round_id / user_id remain and cover lookups.

Existing rows keep the cap of 1, so single-song leagues are unchanged.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d4e2f09a13"
down_revision: Union[str, Sequence[str], None] = "d5f3a9c14b27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "leagues",
        sa.Column(
            "songs_per_submission",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.drop_constraint("uq_submissions_round_user", "submissions", type_="unique")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_unique_constraint("uq_submissions_round_user", "submissions", ["round_id", "user_id"])
    op.drop_column("leagues", "songs_per_submission")
