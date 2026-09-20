"""add session_id to device_push_tokens

Binds a push registration to the login session it was made under
(MysteryMixClub-4vii.36). Additive and nullable: existing rows keep working with
no session (NULL), and a registration made with a token that carries no session
still works, so this is safe to deploy against a live database.

Revision ID: 4acd99f91b51
Revises: 261e97ee359c
Create Date: 2026-09-20 13:27:49.557213

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4acd99f91b51"
down_revision: Union[str, Sequence[str], None] = "261e97ee359c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "device_push_tokens",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_device_push_tokens_session_id_sessions",
        "device_push_tokens",
        "sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_device_push_tokens_session_id"),
        "device_push_tokens",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_device_push_tokens_session_id"), table_name="device_push_tokens")
    op.drop_constraint(
        "fk_device_push_tokens_session_id_sessions", "device_push_tokens", type_="foreignkey"
    )
    op.drop_column("device_push_tokens", "session_id")
