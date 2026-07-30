"""oauth callback rate limiting: oauth_callback_attempts (MysteryMixClub-ali8.8)

Revision ID: 166abbcd848c
Revises: c8e1a4b60d75
Create Date: 2026-07-29 22:17:04.645020

Additive only. ``oauth_callback_attempts`` mirrors ``login_attempts``'
shape (id, a keyed column, created_at + composite index) but keyed by
client IP rather than email: ``/auth/google/callback`` has no email to key
on until *after* the call being rate-limited, so the per-email pattern
every other auth endpoint uses doesn't transfer.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "166abbcd848c"
down_revision: Union[str, Sequence[str], None] = "c8e1a4b60d75"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "oauth_callback_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ip", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_oauth_callback_attempts_ip_created_at",
        "oauth_callback_attempts",
        ["ip", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_oauth_callback_attempts_ip_created_at", table_name="oauth_callback_attempts")
    op.drop_table("oauth_callback_attempts")
