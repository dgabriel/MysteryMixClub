"""password auth: users.password_hash, password_reset_tokens, login_attempts (MysteryMixClub-ali8.1, ADR 0007)

Revision ID: b7d3f5a9c204
Revises: a4f7c2e9d1b3
Create Date: 2026-07-27 00:00:00.000000

Additive only — ``users.password_hash`` is nullable so every existing
magic-link-only account is untouched and keeps working exactly as before.

``password_reset_tokens`` mirrors ``magic_link_tokens`` (hashed, expiring,
hard-deleted on use) minus its vestigial ``used`` flag. ``login_attempts``
records only FAILED password logins so the login endpoint can rate-limit by
counting rows in a window, the same mechanism ``/auth/request`` already uses
against ``magic_link_tokens``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7d3f5a9c204"
down_revision: Union[str, Sequence[str], None] = "a4f7c2e9d1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("password_hash", sa.String(), nullable=True))

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_password_reset_tokens_email"), "password_reset_tokens", ["email"], unique=False
    )
    op.create_index(
        op.f("ix_password_reset_tokens_token_hash"),
        "password_reset_tokens",
        ["token_hash"],
        unique=False,
    )

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Composite rather than email-only: every read filters on both columns
    # ("this email, inside the window"), and email leads so the index still
    # serves the delete-by-email on successful login and account purge.
    op.create_index(
        "ix_login_attempts_email_created_at",
        "login_attempts",
        ["email", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_login_attempts_email_created_at", table_name="login_attempts")
    op.drop_table("login_attempts")
    op.drop_index(op.f("ix_password_reset_tokens_token_hash"), table_name="password_reset_tokens")
    op.drop_index(op.f("ix_password_reset_tokens_email"), table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_column("users", "password_hash")
