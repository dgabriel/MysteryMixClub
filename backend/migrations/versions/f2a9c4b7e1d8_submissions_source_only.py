"""submissions: nullable isrc + source_key for source-only tracks (MYS-201)

Lets a submission be identified by EITHER an ISRC (catalog track) or a
``source_key`` (a Bandcamp/YouTube-only track with no catalog ISRC). Additive
and live-safe for the beta on staging:

* ``isrc`` DROP NOT NULL — a metadata-only catalog change, no table rewrite.
* ``source_key`` added nullable with no default — no rewrite, no backfill.
* ``ck_submissions_isrc_or_source`` added ``NOT VALID`` first (brief ACCESS
  EXCLUSIVE, no scan) then ``VALIDATE`` separately (SHARE UPDATE EXCLUSIVE,
  which still allows concurrent reads and writes). Every existing row has an
  ISRC, so validation passes.

The downgrade is honest and delete-free: re-imposing ``NOT NULL`` on ``isrc``
is impossible while any source-only row exists, so it refuses loudly rather than
dropping or coercing data.

Revision ID: f2a9c4b7e1d8
Revises: c3d1a5b9e7f2
Create Date: 2026-07-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a9c4b7e1d8"
down_revision: Union[str, Sequence[str], None] = "c3d1a5b9e7f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHECK = "ck_submissions_isrc_or_source"


def upgrade() -> None:
    op.alter_column("submissions", "isrc", existing_type=sa.String(), nullable=True)
    op.add_column("submissions", sa.Column("source_key", sa.Text(), nullable=True))
    op.execute(
        f"ALTER TABLE submissions ADD CONSTRAINT {_CHECK} "
        "CHECK (isrc IS NOT NULL OR source_key IS NOT NULL) NOT VALID"
    )
    op.execute(f"ALTER TABLE submissions VALIDATE CONSTRAINT {_CHECK}")


def downgrade() -> None:
    # Re-imposing NOT NULL requires every row to have an ISRC. Source-only rows
    # (isrc NULL) cannot be represented in the pre-migration schema, so refuse
    # rather than silently drop or coerce them.
    null_isrcs = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM submissions WHERE isrc IS NULL"))
        .scalar_one()
    )
    if null_isrcs:
        raise RuntimeError(
            f"cannot downgrade: {null_isrcs} source-only submission(s) have no ISRC and "
            "would violate the restored NOT NULL. Resolve or remove them before downgrading."
        )
    op.drop_constraint(_CHECK, "submissions", type_="check")
    op.drop_column("submissions", "source_key")
    op.alter_column("submissions", "isrc", existing_type=sa.String(), nullable=False)
