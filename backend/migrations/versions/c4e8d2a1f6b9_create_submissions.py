"""create submissions

Revision ID: c4e8d2a1f6b9
Revises: b7f3c1a9d2e4
Create Date: 2026-06-14 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c4e8d2a1f6b9"
down_revision: Union[str, Sequence[str], None] = "b7f3c1a9d2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "submissions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("round_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("isrc", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("artist", sa.String(), nullable=False),
        sa.Column("album", sa.String(), nullable=True),
        sa.Column("album_art_url", sa.String(), nullable=True),
        sa.Column("odesli_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column(
            "participation_mode", sa.String(), server_default=sa.text("'playing'"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["rounds.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("round_id", "user_id", name="uq_submissions_round_user"),
    )
    op.create_index(op.f("ix_submissions_round_id"), "submissions", ["round_id"], unique=False)
    op.create_index(op.f("ix_submissions_user_id"), "submissions", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_submissions_user_id"), table_name="submissions")
    op.drop_index(op.f("ix_submissions_round_id"), table_name="submissions")
    op.drop_table("submissions")
