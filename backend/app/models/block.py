import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Block(Base):
    """A member's persisted block of another member (MysteryMixClub-4vii.42) --
    App Store Guideline 1.2 requires the ability to block abusive users, not
    just to report content.

    One row per (blocker, blocked) pair. One-directional and quiet: only the
    blocker's own reads are filtered (the blocked member's notes and submit
    attribution never reach the blocker); the blocked member's experience is
    unchanged and they are never notified. Semantics live in ADR 0035 and in
    docs/ios/README.md's moderation posture note.

    ON DELETE CASCADE on both sides: interpersonal state has no orphan
    meaning once either account is purged -- unlike reports, which SET NULL so
    the moderation record survives (MysteryMixClub-4vii.38).
    """

    __tablename__ = "blocks"

    blocker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    blocked_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
