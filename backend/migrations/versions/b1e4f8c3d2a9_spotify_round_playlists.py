"""create spotify_round_playlists table

Revision ID: b1e4f8c3d2a9
Revises: a3f7e1b9c4d2
Create Date: 2026-06-28

MYS-89: persist the Spotify playlist ID created for each (round, user) pair so
subsequent generate calls reuse it by ID rather than scanning the library by name.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "b1e4f8c3d2a9"
down_revision: Union[str, Sequence[str], None] = "a3f7e1b9c4d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "spotify_round_playlists",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("round_id", UUID(as_uuid=True), sa.ForeignKey("rounds.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("playlist_id", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("round_id", "user_id", name="uq_spotify_round_playlists_round_user"),
    )
    op.create_index("ix_spotify_round_playlists_round_id", "spotify_round_playlists", ["round_id"])
    op.create_index("ix_spotify_round_playlists_user_id", "spotify_round_playlists", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_spotify_round_playlists_user_id", "spotify_round_playlists")
    op.drop_index("ix_spotify_round_playlists_round_id", "spotify_round_playlists")
    op.drop_table("spotify_round_playlists")
