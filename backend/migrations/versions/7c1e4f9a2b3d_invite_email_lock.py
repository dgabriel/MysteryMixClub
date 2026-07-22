"""invite email lock (MYS-215)

Adds a nullable email column to invites. Set only for a waitlist-issued
invite, to restrict redemption to that one address; null (the existing
behavior) for every other invite. Additive only.

Revision ID: 7c1e4f9a2b3d
Revises: 42875937489b
Create Date: 2026-07-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7c1e4f9a2b3d"
down_revision: Union[str, Sequence[str], None] = "42875937489b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invites", sa.Column("email", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("invites", "email")
