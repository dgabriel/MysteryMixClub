"""users tos_accepted_at

Revision ID: 23cc689cc7f4
Revises: 820c7d69bf4d
Create Date: 2026-07-17

MYS-183: capture consent to the Terms of Service / Privacy Policy. Adds
``users.tos_accepted_at``, nullable with no default — every existing row
(including live beta users on staging) starts NULL and is routed through the
consent gate until they explicitly accept. Additive only, no backfill.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "23cc689cc7f4"
down_revision: Union[str, Sequence[str], None] = "820c7d69bf4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tos_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "tos_accepted_at")
