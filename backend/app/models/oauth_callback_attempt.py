import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OAuthCallbackAttempt(Base):
    """One row per hit on ``/auth/google/callback``, for per-IP rate limiting
    (MysteryMixClub-ali8.8).

    Every other unauthenticated auth endpoint rate-limits per email
    (``login_attempts``, ``magic_link_tokens`` row-counting) — the callback
    has no email until *after* ``exchange_code``, which is exactly the call
    being abused, so that pattern doesn't transfer. This counts rows per IP
    in a time window the same way, storing the raw client IP (see
    ``docs/security/data-residency.md`` for the retention note this implies).

    Unlike ``login_attempts``, a row is recorded on *every* callback hit —
    success or failure — since the thing being throttled is exchange-code
    guessing against the callback itself, not failed credential attempts.
    """

    __tablename__ = "oauth_callback_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ip: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Composite, not ip-only: every read is "this IP, inside the window", so
    # created_at has to be in the index or a busy IP's whole history gets
    # scanned before the time filter applies. Leading on ip also serves the
    # purge job's per-IP cleanup shape if that's ever needed (today it purges
    # by age alone, mirroring purge_login_attempts).
    __table_args__ = (Index("ix_oauth_callback_attempts_ip_created_at", "ip", "created_at"),)
