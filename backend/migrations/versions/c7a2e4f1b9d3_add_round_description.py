"""add rounds.description

Revision ID: c7a2e4f1b9d3
Revises: b2d4e6f8a0c1
Create Date: 2026-06-20 00:00:00.000000

MYS-62: pre-created rounds. Adds the nullable `description` column. The round's
`theme` remains its name/prompt; `description` is optional supporting detail.
The lifecycle gains a `pending` state (pending -> open_submission -> open_voting
-> closed) but the `state` column's server_default ('open_submission') is left
unchanged — bulk-created rounds set state='pending' explicitly, while the
existing single-create path still defaults to 'open_submission'.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7a2e4f1b9d3"
down_revision: Union[str, Sequence[str], None] = "b2d4e6f8a0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("rounds", sa.Column("description", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("rounds", "description")
