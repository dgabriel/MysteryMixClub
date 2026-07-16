"""invites used_at for single-use platform invites

Revision ID: 820c7d69bf4d
Revises: 968194bf004d
Create Date: 2026-07-15 22:26:24.409370

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "820c7d69bf4d"
down_revision: Union[str, Sequence[str], None] = "968194bf004d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    MYS-182 follow-up: a platform (league-less) invite is single-use.
    used_at is stamped when it gates a new account; a league invite never
    sets it and stays multi-use. Additive/backward compatible.
    """
    op.add_column("invites", sa.Column("used_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("invites", "used_at")
