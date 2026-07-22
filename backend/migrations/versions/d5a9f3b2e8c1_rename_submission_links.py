"""rename submissions.odesli_data to platform_links

Revision ID: d5a9f3b2e8c1
Revises: c4e8d2a1f6b9
Create Date: 2026-06-15 00:00:00.000000

MYS-52: cross-platform links are now assembled keyless (Deezer/iTunes exact +
Spotify/YouTube deep links) rather than stored as a raw Odesli payload. The
column now holds a {platform: url} map, so it is renamed to match.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d5a9f3b2e8c1"
down_revision: Union[str, Sequence[str], None] = "c4e8d2a1f6b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("submissions", "odesli_data", new_column_name="platform_links")


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("submissions", "platform_links", new_column_name="odesli_data")
