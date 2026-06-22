"""add spotify_connections and submissions.spotify_track_uri

Revision ID: f4b9d7c2a1e8
Revises: e1a4c7d9f3b6
Create Date: 2026-06-22 00:00:00.000000

MYS-83: per-user Spotify OAuth + create saved playlist for a round.

- ``spotify_connections`` stores one authorized Spotify account per user, with
  the refresh token **encrypted at rest** (it is replayed to Spotify to mint
  access tokens, so it cannot be hashed like the app's own session tokens).
- ``submissions.spotify_track_uri`` caches the ISRC-resolved Spotify track URI
  per submission (mirrors the ``youtube_video_id`` cache from MYS-78), so
  playlist creation does no repeat search lookups. Nullable: unresolved tracks
  stay null and surface as "unmatched".
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f4b9d7c2a1e8"
down_revision: Union[str, Sequence[str], None] = "e1a4c7d9f3b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("submissions", sa.Column("spotify_track_uri", sa.String(), nullable=True))
    op.create_table(
        "spotify_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("spotify_user_id", sa.String(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_spotify_connections_user"),
    )
    op.create_index(
        op.f("ix_spotify_connections_user_id"), "spotify_connections", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_spotify_connections_user_id"), table_name="spotify_connections")
    op.drop_table("spotify_connections")
    op.drop_column("submissions", "spotify_track_uri")
