"""create notes

Revision ID: a3f9b1c4d7e2
Revises: f1c7e0a3b6d2
Create Date: 2026-06-15 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3f9b1c4d7e2"
down_revision: Union[str, Sequence[str], None] = "f1c7e0a3b6d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("round_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("submission_id", sa.UUID(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
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
            ["author_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notes_round_id"), "notes", ["round_id"], unique=False)
    op.create_index(op.f("ix_notes_author_id"), "notes", ["author_id"], unique=False)
    op.create_index(op.f("ix_notes_submission_id"), "notes", ["submission_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_notes_submission_id"), table_name="notes")
    op.drop_index(op.f("ix_notes_author_id"), table_name="notes")
    op.drop_index(op.f("ix_notes_round_id"), table_name="notes")
    op.drop_table("notes")
