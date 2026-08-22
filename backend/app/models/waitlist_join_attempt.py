import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WaitlistJoinAttempt(Base):
    """One row per hit on ``POST /waitlist``, for per-IP rate limiting
    (MysteryMixClub-dicr).

    ``waitlist.py``'s original limiter was an in-memory module-level dict,
    correct only under a single worker process. That precondition broke when
    prod moved to multi-worker gunicorn (MYS-259) — each worker keeps its own
    copy of the bucket, so the effective limit becomes N x the intended one
    and resets on every worker restart/deploy. This mirrors
    ``OAuthCallbackAttempt``'s shape (row-per-hit, counted in a time window,
    keyed by IP rather than email since the endpoint is unauthenticated and
    each request can target a different address) so the limit is shared
    across every worker via the database instead of process memory.
    """

    __tablename__ = "waitlist_join_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ip: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Composite, not ip-only: every read is "this IP, inside the window", so
    # created_at has to be in the index or a busy IP's whole history gets
    # scanned before the time filter applies.
    __table_args__ = (Index("ix_waitlist_join_attempts_ip_created_at", "ip", "created_at"),)
