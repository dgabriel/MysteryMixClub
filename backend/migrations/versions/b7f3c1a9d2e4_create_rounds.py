"""create rounds

Revision ID: b7f3c1a9d2e4
Revises: e9eae27f27f7
Create Date: 2026-06-14 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7f3c1a9d2e4"
down_revision: Union[str, Sequence[str], None] = "e9eae27f27f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "rounds",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("league_id", sa.UUID(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("theme", sa.String(), nullable=False),
        sa.Column(
            "state", sa.String(), server_default=sa.text("'open_submission'"), nullable=False
        ),
        sa.Column("submission_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voting_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("votes_per_player", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["league_id"],
            ["leagues.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("league_id", "round_number", name="uq_rounds_league_number"),
    )
    op.create_index(op.f("ix_rounds_league_id"), "rounds", ["league_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_rounds_league_id"), table_name="rounds")
    op.drop_table("rounds")
