"""rename ck_league_members_role check constraint (MYS-195 R3/R4 cleanup)

Metadata-only rename (ACCESS EXCLUSIVE for milliseconds, no table rewrite, no
data movement). The MYS-196 cutover deliberately left this one constraint name
on the old vocabulary, deferring it to the R3/R4 Python identifier cleanup —
this migration finishes that: the model's ``__table_args__`` CheckConstraint
name is renamed alongside it, in the same commit as the model class rename
(``LeagueMember`` -> ``ClubMember``).

Revision ID: a1b2c3d4e5f6
Revises: f2a9c4b7e1d8
Create Date: 2026-07-20
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f2a9c4b7e1d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE club_members RENAME CONSTRAINT ck_league_members_role TO ck_club_members_role"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE club_members RENAME CONSTRAINT ck_club_members_role TO ck_league_members_role"
    )
