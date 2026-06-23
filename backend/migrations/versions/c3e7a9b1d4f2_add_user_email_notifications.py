"""add users.email_notifications

Revision ID: c3e7a9b1d4f2
Revises: f4b9d7c2a1e8
Create Date: 2026-06-23 00:00:00.000000

MYS-109: per-user email notification preference (default on). Drives whether
round-lifecycle emails are sent; toggled off in-app or via the one-click
unsubscribe link in each email. server_default true so existing rows opt in.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3e7a9b1d4f2"
down_revision: Union[str, Sequence[str], None] = "f4b9d7c2a1e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column(
            "email_notifications",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "email_notifications")
