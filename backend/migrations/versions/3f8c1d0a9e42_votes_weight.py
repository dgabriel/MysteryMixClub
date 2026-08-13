"""add votes.weight

Revision ID: 3f8c1d0a9e42
Revises: 166abbcd848c
Create Date: 2026-08-13 00:00:00.000000

MysteryMixClub-ih3l / ADR 0014: weighted voting. A player may spend more than one
of their votes on a single song, so a vote carries a count rather than being a
bare fact. Additive on purpose — UNIQUE(voter_id, submission_id) stays, so there
is still exactly one row per (voter, submission) and every existing vote is a
valid weighted vote at weight 1. Server default 1 so the backfill is free on
live prod data; the CHECK keeps a zero or negative weight out of the table,
since "no vote" is the absence of a row, not a row worth nothing.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3f8c1d0a9e42"
down_revision: Union[str, Sequence[str], None] = "166abbcd848c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "votes",
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint("ck_votes_weight_positive", "votes", "weight >= 1")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_votes_weight_positive", "votes", type_="check")
    op.drop_column("votes", "weight")
