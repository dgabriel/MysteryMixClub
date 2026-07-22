"""create votes

Revision ID: f1c7e0a3b6d2
Revises: d5a9f3b2e8c1
Create Date: 2026-06-15 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1c7e0a3b6d2"
down_revision: Union[str, Sequence[str], None] = "d5a9f3b2e8c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "votes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("round_id", sa.UUID(), nullable=False),
        sa.Column("voter_id", sa.UUID(), nullable=False),
        sa.Column("submission_id", sa.UUID(), nullable=False),
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
            ["voter_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("voter_id", "submission_id", name="uq_votes_voter_submission"),
    )
    op.create_index(op.f("ix_votes_round_id"), "votes", ["round_id"], unique=False)
    op.create_index(op.f("ix_votes_voter_id"), "votes", ["voter_id"], unique=False)
    op.create_index(op.f("ix_votes_submission_id"), "votes", ["submission_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_votes_submission_id"), table_name="votes")
    op.drop_index(op.f("ix_votes_voter_id"), table_name="votes")
    op.drop_index(op.f("ix_votes_round_id"), table_name="votes")
    op.drop_table("votes")
