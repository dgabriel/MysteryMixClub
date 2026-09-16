"""create auth identities

Revision ID: 07a9db76f961
Revises: 80ab60c9ee7b
Create Date: 2026-09-15 23:39:59.356759

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "07a9db76f961"
down_revision: Union[str, Sequence[str], None] = "80ab60c9ee7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "auth_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("provider IN ('google', 'apple')", name="ck_auth_identities_provider"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "subject", name="uq_auth_identities_provider_subject"),
    )
    op.create_index(
        op.f("ix_auth_identities_user_id"), "auth_identities", ["user_id"], unique=False
    )

    # Backfill (MysteryMixClub-4vii.9): every user already linked to a Google
    # account via the legacy users.google_id column gets an equivalent
    # auth_identities row, so the generalized lookup this migration enables
    # sees existing linked accounts from day one -- without this, every
    # already-linked user would appear unlinked to the new code path.
    op.execute(
        """
        INSERT INTO auth_identities (id, user_id, provider, subject, created_at)
        SELECT gen_random_uuid(), id, 'google', google_id, now()
        FROM users
        WHERE google_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_auth_identities_user_id"), table_name="auth_identities")
    op.drop_table("auth_identities")
