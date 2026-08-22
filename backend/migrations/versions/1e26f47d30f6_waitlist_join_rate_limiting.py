"""waitlist join rate limiting: waitlist_join_attempts (MysteryMixClub-dicr)

Revision ID: 1e26f47d30f6
Revises: a7d419c6b038
Create Date: 2026-08-22

Additive only. ``waitlist_join_attempts`` mirrors ``oauth_callback_attempts``'
shape (id, ip, created_at + composite index) — the same reason applies:
``POST /waitlist`` is unauthenticated and each request can target a
different email, so a per-email limiter doesn't transfer. Replaces the
in-memory per-process rate limiter in ``waitlist.py``, which stopped being
correct once prod moved to multi-worker gunicorn (MYS-259).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1e26f47d30f6"
down_revision: Union[str, Sequence[str], None] = "a7d419c6b038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "waitlist_join_attempts",
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
        "ix_waitlist_join_attempts_ip_created_at",
        "waitlist_join_attempts",
        ["ip", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_waitlist_join_attempts_ip_created_at", table_name="waitlist_join_attempts")
    op.drop_table("waitlist_join_attempts")
