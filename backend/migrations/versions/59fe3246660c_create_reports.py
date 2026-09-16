"""create reports

Revision ID: 59fe3246660c
Revises: 577179dfbf16
Create Date: 2026-09-15 22:18:16.386913

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "59fe3246660c"
down_revision: Union[str, Sequence[str], None] = "577179dfbf16"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("reporter_id", sa.UUID(), nullable=False),
        sa.Column("reported_user_id", sa.UUID(), nullable=False),
        sa.Column("club_id", sa.UUID(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("content_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), server_default=sa.text("'open'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("content_type IN ('note')", name="ck_reports_content_type"),
        sa.CheckConstraint(
            "reason IN ('inappropriate_content', 'harassment', 'spam', 'other')",
            name="ck_reports_reason",
        ),
        sa.CheckConstraint("status IN ('open', 'reviewed')", name="ck_reports_status"),
        sa.ForeignKeyConstraint(
            ["club_id"],
            ["clubs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reported_user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reports_club_id"), "reports", ["club_id"], unique=False)
    op.create_index(
        op.f("ix_reports_reported_user_id"), "reports", ["reported_user_id"], unique=False
    )
    op.create_index(op.f("ix_reports_reporter_id"), "reports", ["reporter_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_reports_reporter_id"), table_name="reports")
    op.drop_index(op.f("ix_reports_reported_user_id"), table_name="reports")
    op.drop_index(op.f("ix_reports_club_id"), table_name="reports")
    op.drop_table("reports")
