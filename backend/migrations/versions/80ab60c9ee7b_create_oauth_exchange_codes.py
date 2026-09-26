"""create oauth exchange codes

Revision ID: 80ab60c9ee7b
Revises: 59fe3246660c
Create Date: 2026-09-15 23:03:37.084648

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "80ab60c9ee7b"
down_revision: Union[str, Sequence[str], None] = "59fe3246660c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "oauth_exchange_codes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_oauth_exchange_codes_code_hash"),
        "oauth_exchange_codes",
        ["code_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_exchange_codes_user_id"), "oauth_exchange_codes", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_oauth_exchange_codes_user_id"), table_name="oauth_exchange_codes")
    op.drop_index(op.f("ix_oauth_exchange_codes_code_hash"), table_name="oauth_exchange_codes")
    op.drop_table("oauth_exchange_codes")
