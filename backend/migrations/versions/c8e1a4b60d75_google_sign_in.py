"""google sign-in: users.google_id (MysteryMixClub-ali8.2, ADR 0007)

Revision ID: c8e1a4b60d75
Revises: b7d3f5a9c204
Create Date: 2026-07-28 00:00:00.000000

Additive only — nullable, so every existing account is untouched and keeps
working exactly as before. Unique so one Google account can never be linked to
two app users; NULL is exempt from a UNIQUE constraint in Postgres, so any
number of accounts may have no Google identity.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c8e1a4b60d75"
down_revision: Union[str, Sequence[str], None] = "b7d3f5a9c204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("google_id", sa.String(), nullable=True))
    op.create_unique_constraint("uq_users_google_id", "users", ["google_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_users_google_id", "users", type_="unique")
    op.drop_column("users", "google_id")
