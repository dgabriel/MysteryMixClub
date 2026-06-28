"""add unique constraint to league_members (league_id, user_id)

Revision ID: a3f7e1b9c4d2
Revises: e2c9a7f14b30
Create Date: 2026-06-28

MYS-32: prevents concurrent invite-accept calls from inserting duplicate
membership rows for the same (league_id, user_id) pair.  The application
layer already tries to avoid duplicates, but without a DB constraint two
racing transactions could both read "no membership found" and both INSERT.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a3f7e1b9c4d2"
down_revision: Union[str, Sequence[str], None] = "e2c9a7f14b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_league_members_league_user", "league_members", ["league_id", "user_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_league_members_league_user", "league_members", type_="unique")
