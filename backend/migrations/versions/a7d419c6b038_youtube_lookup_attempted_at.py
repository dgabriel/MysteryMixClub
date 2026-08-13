"""add submissions.youtube_lookup_attempted_at, allow playlist_jobs provider 'youtube'

Revision ID: a7d419c6b038
Revises: 3f8c1d0a9e42
Create Date: 2026-08-13 00:00:00.000000

MysteryMixClub-6jzl / ADR 0015. Two changes, both additive:

1. ``submissions.youtube_lookup_attempted_at`` — records that a YouTube resolve
   was attempted, on success and on miss alike. Previously a miss left
   ``youtube_video_id`` NULL, which is indistinguishable from "never tried", so
   both playlist read paths re-ran the lookup on every single request forever.

2. ``ck_playlist_jobs_provider`` widened to accept ``'youtube'`` so the backfill
   can run as an ordinary job on the existing queue instead of inline in a GET.

No data migration is needed for (1): an already-resolved row has a non-NULL
``youtube_video_id``, which excludes it from the backfill query on its own,
so leaving its ``attempted_at`` NULL is harmless.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7d419c6b038"
down_revision: Union[str, Sequence[str], None] = "3f8c1d0a9e42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "submissions",
        sa.Column("youtube_lookup_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index: the backfill only ever scans unresolved, never-attempted,
    # non-source-only rows, and that set shrinks to near-empty as it drains.
    op.create_index(
        "ix_submissions_youtube_backfill_pending",
        "submissions",
        ["mix_id"],
        postgresql_where=sa.text(
            "youtube_video_id IS NULL "
            "AND youtube_lookup_attempted_at IS NULL "
            "AND source_key IS NULL"
        ),
    )
    op.drop_constraint("ck_playlist_jobs_provider", "playlist_jobs", type_="check")
    op.create_check_constraint(
        "ck_playlist_jobs_provider",
        "playlist_jobs",
        "provider IN ('spotify', 'apple', 'youtube')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Any 'youtube' rows must go before the narrower constraint can be restored.
    op.execute("DELETE FROM playlist_jobs WHERE provider = 'youtube'")
    op.drop_constraint("ck_playlist_jobs_provider", "playlist_jobs", type_="check")
    op.create_check_constraint(
        "ck_playlist_jobs_provider",
        "playlist_jobs",
        "provider IN ('spotify', 'apple')",
    )
    op.drop_index("ix_submissions_youtube_backfill_pending", table_name="submissions")
    op.drop_column("submissions", "youtube_lookup_attempted_at")
