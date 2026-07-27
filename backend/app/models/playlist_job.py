import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# MYS-258 / ADR 0006 (Slice 1). "apple" is a valid value here — the schema and
# enqueue_playlist_job() are provider-generic — but no call site enqueues an
# Apple job yet: POST /mixes/{id}/apple-playlist's Music User Token is a
# per-request credential that is explicitly never persisted (see
# app/services/apple_playlist_generation.py's module docstring), which
# conflicts with handing it to a worker that may run after the request has
# ended. That conflict is flagged, not silently worked around; the endpoint
# stays synchronous pending an explicit decision on how (or whether) to queue
# per-player Apple generation.
PLAYLIST_JOB_PROVIDERS = ("spotify", "apple")
PLAYLIST_JOB_STATUSES = ("queued", "running", "complete", "failed")


class PlaylistJob(Base):
    """One playlist-generation request, queued for the background worker
    (``app.jobs.playlist_worker``) instead of running inline in the request/job
    path (ADR 0006, MYS-258 Slice 1).

    The unique index below is scoped to non-terminal statuses (a *partial*
    unique index, not a plain ``UNIQUE(mix_id, provider)``) so a double-enqueue
    (e.g. two admins racing the same PATCH) collapses to one row, while a
    legitimate re-run after a prior job already reached ``complete``/``failed``
    is never blocked by it.
    """

    __tablename__ = "playlist_jobs"
    __table_args__ = (
        CheckConstraint("provider IN ('spotify', 'apple')", name="ck_playlist_jobs_provider"),
        CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'failed')",
            name="ck_playlist_jobs_status",
        ),
        Index(
            "uq_playlist_jobs_active_mix_provider",
            "mix_id",
            "provider",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mix_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mixes.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="queued", server_default=text("'queued'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Populated on a "failed" row with the exception text (truncated) — the
    # worker's own diagnostic trail; not surfaced to end users in Slice 1
    # (dead-letter *visibility* beyond this queryable column is deferred, see
    # ADR 0006).
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
