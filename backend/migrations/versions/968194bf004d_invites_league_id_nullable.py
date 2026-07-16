"""invites league_id nullable

Revision ID: 968194bf004d
Revises: e00802169d70
Create Date: 2026-07-15 21:59:07.995924

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "968194bf004d"
down_revision: Union[str, Sequence[str], None] = "e00802169d70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    MYS-182: a null league_id marks a platform (admin-generated, league-less)
    invite — grants signup only, no league attachment. Additive/backward
    compatible: existing rows keep their non-null values.
    """
    op.alter_column("invites", "league_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("invites", "league_id", existing_type=sa.UUID(), nullable=False)
