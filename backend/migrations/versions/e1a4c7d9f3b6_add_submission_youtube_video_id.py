"""add submissions.youtube_video_id

Revision ID: e1a4c7d9f3b6
Revises: d8b3f0c2e5a7
Create Date: 2026-06-21 00:00:00.000000

MYS-78: YouTube playlist link. The stored YouTube platform_link is only a search
deep-link with no video id, so the playlist endpoint resolves each track's real
YouTube watch URL via Odesli on demand and caches the parsed video id here to
avoid repeat upstream calls. Nullable: unresolved tracks stay null.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1a4c7d9f3b6"
down_revision: Union[str, Sequence[str], None] = "d8b3f0c2e5a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("submissions", sa.Column("youtube_video_id", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("submissions", "youtube_video_id")
