"""deadline schema for datetime-based round closing

Revision ID: c7d2e9f1a4b8
Revises: b1e4f8c3d2a9
Create Date: 2026-07-01

MYS-159: rounds close on quorum OR a configurable deadline (epic MYS-158). Adds
the per-league deadline windows (in days) used to stamp each round's
submission/voting deadline when it opens, plus the per-round "already notified"
timestamps the later deadline cron (MYS-145) will use to fire warnings exactly
once. Additive only — real beta users live on staging, so no destructive ops
and no backfill.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d2e9f1a4b8"
down_revision: Union[str, Sequence[str], None] = "b1e4f8c3d2a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leagues",
        sa.Column(
            "submission_deadline_days",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
    )
    op.add_column(
        "leagues",
        sa.Column(
            "voting_deadline_days",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
    )
    op.add_column(
        "rounds",
        sa.Column("submission_warning_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rounds",
        sa.Column("voting_warning_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rounds",
        sa.Column("empty_round_notice_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rounds", "empty_round_notice_sent_at")
    op.drop_column("rounds", "voting_warning_sent_at")
    op.drop_column("rounds", "submission_warning_sent_at")
    op.drop_column("leagues", "voting_deadline_days")
    op.drop_column("leagues", "submission_deadline_days")
