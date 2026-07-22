"""create leagues and league_members

Revision ID: dbb002cd11b8
Revises: fd788b42cd53
Create Date: 2026-06-08 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "dbb002cd11b8"
down_revision: Union[str, Sequence[str], None] = "fd788b42cd53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "leagues",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("organizer_id", sa.UUID(), nullable=False),
        sa.Column("total_rounds", sa.Integer(), nullable=False),
        sa.Column("votes_per_player", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("current_round", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("state", sa.String(), server_default=sa.text("'active'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organizer_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_leagues_organizer_id"), "leagues", ["organizer_id"], unique=False)
    op.create_table(
        "league_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("league_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["league_id"],
            ["leagues.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_league_members_league_id"), "league_members", ["league_id"], unique=False
    )
    op.create_index(op.f("ix_league_members_user_id"), "league_members", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_league_members_user_id"), table_name="league_members")
    op.drop_index(op.f("ix_league_members_league_id"), table_name="league_members")
    op.drop_table("league_members")
    op.drop_index(op.f("ix_leagues_organizer_id"), table_name="leagues")
    op.drop_table("leagues")
