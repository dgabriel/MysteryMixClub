import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Report(Base):
    """A member's report of another member's user-generated content
    (MysteryMixClub-4vii.13) -- App Store Guideline 1.2's minimum bar for a
    UGC app: a way to flag objectionable content for review. v1 is
    deliberately just persistence; there's no admin console yet, so review
    happens by querying this table directly (see docs/ios/README.md's
    moderation note for the operational process)."""

    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint("content_type IN ('note')", name="ck_reports_content_type"),
        CheckConstraint(
            "reason IN ('inappropriate_content', 'harassment', 'spam', 'other')",
            name="ck_reports_reason",
        ),
        CheckConstraint("status IN ('open', 'reviewed')", name="ck_reports_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reporter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # Denormalized at write time from the reported content's own author, so a
    # review pass never needs a join back through every possible content type
    # to find out who's being reported.
    reported_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id"), nullable=False, index=True
    )
    # 'note' only for v1 -- the one freeform, attributed-to-a-real-name UGC
    # surface a member sees from other members. Extend the check constraint
    # (and this comment) before adding a second content_type.
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    content_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="open", server_default=text("'open'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
