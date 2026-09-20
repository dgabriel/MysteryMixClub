"""add push nudge markers and voting_opened_at to mixes

Bookkeeping for the halfway, due-morning and last-few push nudges
(MysteryMixClub-bfqo). Additive and nullable, so it is safe to deploy against a
live database: a NULL marker means "not sent yet", and a NULL voting_opened_at
(a mix already voting at deploy) just gets no voting halfway nudge.

Revision ID: 8b3d5e7a9c21
Revises: 4acd99f91b51
Create Date: 2026-09-20 16:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b3d5e7a9c21"
down_revision: Union[str, Sequence[str], None] = "4acd99f91b51"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    "voting_opened_at",
    "push_submission_halfway_sent_at",
    "push_voting_halfway_sent_at",
    "push_submission_due_morning_sent_at",
    "push_voting_due_morning_sent_at",
    "push_submission_last_few_sent_at",
)


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column("mixes", sa.Column(name, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("mixes", name)
