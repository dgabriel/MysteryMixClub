"""rounds submission_opened_at

Revision ID: e2c9a7f14b30
Revises: b7d4e2f09a13
Create Date: 2026-06-27 00:00:00.000000

MYS-69: auto-advance round lifecycle.

* rounds.submission_opened_at — when the round entered open_submission. Used to
  scope the submission-quorum to members present when the window opened.

Backfill: existing non-pending rounds get submission_opened_at = now() so
in-flight rounds have a baseline open time. created_at is league-creation time
(rounds are pre-created pending), which predates when members joined, so it would
leave an open round with an empty active-at-open set that never auto-advances;
now() makes the current membership the baseline. Pending rounds stay NULL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2c9a7f14b30"
down_revision: Union[str, Sequence[str], None] = "b7d4e2f09a13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "rounds",
        sa.Column("submission_opened_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE rounds SET submission_opened_at = now() WHERE state != 'pending'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("rounds", "submission_opened_at")
