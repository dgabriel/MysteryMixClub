"""create playlist_jobs (MYS-258, ADR 0006, Slice 1)

Revision ID: a4f7c2e9d1b3
Revises: e91a4c2f6b0d
Create Date: 2026-07-26 00:00:00.000000

Postgres-backed background job queue for playlist generation (ADR 0006, no
Redis): one row per (mix, provider) generation request, enqueued by
``app.services.playlist_jobs.enqueue_playlist_job`` and dequeued by the new
``app.jobs.playlist_worker`` process via ``LISTEN``/``NOTIFY`` +
``SELECT ... FOR UPDATE SKIP LOCKED``.

The unique index is *partial* (``WHERE status IN ('queued', 'running')``),
not a plain ``UNIQUE(mix_id, provider)``: it collapses a double-enqueue to one
row while a job is still live, but never blocks a legitimate re-run once a
prior job for the same (mix, provider) has reached a terminal
``complete``/``failed`` state.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a4f7c2e9d1b3"
down_revision: Union[str, Sequence[str], None] = "e91a4c2f6b0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "playlist_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("mix_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("provider IN ('spotify', 'apple')", name="ck_playlist_jobs_provider"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'failed')",
            name="ck_playlist_jobs_status",
        ),
        sa.ForeignKeyConstraint(["mix_id"], ["mixes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_playlist_jobs_mix_id"), "playlist_jobs", ["mix_id"], unique=False)
    op.create_index(
        "uq_playlist_jobs_active_mix_provider",
        "playlist_jobs",
        ["mix_id", "provider"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_playlist_jobs_active_mix_provider", table_name="playlist_jobs")
    op.drop_index(op.f("ix_playlist_jobs_mix_id"), table_name="playlist_jobs")
    op.drop_table("playlist_jobs")
