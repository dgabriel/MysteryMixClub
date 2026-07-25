"""notes one per author per submission (MYS-257)

Revision ID: e91a4c2f6b0d
Revises: 7c1e4f9a2b3d
Create Date: 2026-07-25 00:00:00.000000

Prod/staging already have live rows from before this rule existed, so
pre-existing (author_id, submission_id) duplicates are collapsed to the
earliest note (by created_at, then id) before the constraint is added —
otherwise the ADD CONSTRAINT fails outright on any duplicate.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e91a4c2f6b0d"
down_revision: Union[str, Sequence[str], None] = "7c1e4f9a2b3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        DELETE FROM notes n
        USING (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY author_id, submission_id
                       ORDER BY created_at ASC, id ASC
                   ) AS rn
            FROM notes
        ) dup
        WHERE n.id = dup.id AND dup.rn > 1
        """
    )
    op.create_unique_constraint(
        "uq_notes_author_submission", "notes", ["author_id", "submission_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_notes_author_submission", "notes", type_="unique")
