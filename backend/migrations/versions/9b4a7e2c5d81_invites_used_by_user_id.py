"""invites used_by_user_id

Revision ID: 9b4a7e2c5d81
Revises: 23cc689cc7f4
Create Date: 2026-07-17

Fixes a bug found while testing MYS-183: a brand-new user signing up via a
platform (league-less) invite gets bounced through /onboarding, and the
stashed pendingInvitePath then redirects back to the now-consumed invite
link — which 410s for everyone, including the very user who just used it,
because there was no way to tell the two apart. Adds
``invites.used_by_user_id`` so the preview endpoint can allow the same
caller who consumed it through (mirroring the existing already-member
bypass for league invites), while a different visitor still sees the
correct expired state. Additive only, nullable, no backfill.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "9b4a7e2c5d81"
down_revision: Union[str, Sequence[str], None] = "23cc689cc7f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invites",
        sa.Column("used_by_user_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_invites_used_by_user_id_users",
        "invites",
        "users",
        ["used_by_user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_invites_used_by_user_id_users", "invites", type_="foreignkey")
    op.drop_column("invites", "used_by_user_id")
