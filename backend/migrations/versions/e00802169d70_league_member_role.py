"""league member role (co-organizer)

Revision ID: e00802169d70
Revises: c7d2e9f1a4b8
Create Date: 2026-07-04

MYS-99: an organizer may promote another active member to co-organizer, with
full operational parity to the organizer (everywhere ``_load_league_as_organizer``
gates). Adds ``league_members.role`` (``member`` | ``admin``), defaulting every
existing and future row to ``member``. Additive only, with a NOT NULL server
default and a CHECK constraint enforced at the DB layer — real beta users live
on staging, so no destructive ops and no backfill required.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e00802169d70"
down_revision: Union[str, Sequence[str], None] = "c7d2e9f1a4b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "league_members",
        sa.Column("role", sa.Text(), nullable=False, server_default=sa.text("'member'")),
    )
    op.create_check_constraint(
        "ck_league_members_role",
        "league_members",
        "role IN ('member', 'admin')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_league_members_role", "league_members", type_="check")
    op.drop_column("league_members", "role")
