"""club deadline weekly anchor mode (ADR 0021, MysteryMixClub-z845)

Revision ID: 577179dfbf16
Revises: 1e26f47d30f6
Create Date: 2026-09-09

Additive only. Adds an alternate, opt-in deadline scheme alongside the
existing submission_window_hours/voting_window_hours columns: a club can pin
both phases to a fixed weekday + time in a chosen IANA timezone instead of a
rolling N-hour window. deadline_mode defaults to "duration" and timezone
defaults to "UTC", so every existing club is unaffected until an organizer
opts in; the four weekday/time columns stay NULL until then.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "577179dfbf16"
down_revision: Union[str, Sequence[str], None] = "1e26f47d30f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "clubs",
        sa.Column(
            "deadline_mode",
            sa.String(),
            nullable=False,
            server_default=sa.text("'duration'"),
        ),
    )
    op.add_column(
        "clubs",
        sa.Column(
            "timezone",
            sa.String(),
            nullable=False,
            server_default=sa.text("'UTC'"),
        ),
    )
    op.add_column("clubs", sa.Column("submission_weekday", sa.Integer(), nullable=True))
    op.add_column("clubs", sa.Column("submission_time", sa.Time(), nullable=True))
    op.add_column("clubs", sa.Column("voting_weekday", sa.Integer(), nullable=True))
    op.add_column("clubs", sa.Column("voting_time", sa.Time(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("clubs", "voting_time")
    op.drop_column("clubs", "voting_weekday")
    op.drop_column("clubs", "submission_time")
    op.drop_column("clubs", "submission_weekday")
    op.drop_column("clubs", "timezone")
    op.drop_column("clubs", "deadline_mode")
