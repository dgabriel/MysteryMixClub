"""per-league vibe mode

Revision ID: d5f3a9c14b27
Revises: c3e7a9b1d4f2
Create Date: 2026-06-26 00:00:00.000000

MYS-112 / MYS-60: participation mode becomes per-league.

* leagues.default_vibe_mode — admin-set default for the league (server_default
  false).
* league_members.vibe_mode — the member's per-league setting, seeded from the
  league default at join (server_default false).
* drop users.default_vibe_mode — superseded by the per-league setting.

Existing rows take the false (Playing) default. The user-level flag is dropped
rather than migrated; pre-beta there is no meaningful data to carry over.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5f3a9c14b27"
down_revision: Union[str, Sequence[str], None] = "c3e7a9b1d4f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "leagues",
        sa.Column(
            "default_vibe_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "league_members",
        sa.Column(
            "vibe_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.drop_column("users", "default_vibe_mode")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "users",
        sa.Column(
            "default_vibe_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.drop_column("league_members", "vibe_mode")
    op.drop_column("leagues", "default_vibe_mode")
