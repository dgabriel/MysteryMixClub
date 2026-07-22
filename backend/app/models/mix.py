import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Mix lifecycle states (technical-design §6). Forward-only:
# pending -> open_submission -> open_voting -> closed.
MIX_STATES = ("pending", "open_submission", "open_voting", "closed")


class Mix(Base):
    # Renamed from Round (MYS-195, R3/R4 identifier cleanup) — the DB was
    # already renamed to club/mix vocabulary in MYS-196, so the attribute names
    # now match the column names directly with no seam.
    __tablename__ = "mixes"
    # A club's mix numbers are unique and sequential.
    __table_args__ = (UniqueConstraint("club_id", "mix_number", name="uq_mixes_club_number"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id"), nullable=False, index=True
    )
    mix_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Nullable: mixes are auto-generated at club creation without a theme; the
    # organizer fills it in while the mix is still pending (MYS-62).
    theme: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(
        String, nullable=False, default="open_submission", server_default=text("'open_submission'")
    )
    submission_deadline: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voting_deadline: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    votes_per_player: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # When the mix entered open_submission (MYS-69). Auto-advance scopes its
    # quorum to members present at this moment; nullable because pending mixes
    # have not opened yet.
    submission_opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Deadline-notification bookkeeping (MYS-159). The deadline cron (MYS-145)
    # stamps each of these the one time it sends the corresponding notice, so a
    # warning / empty-mix notice fires exactly once per mix. Nullable: unset
    # until (and unless) that notice goes out.
    submission_warning_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voting_warning_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Column name unchanged (MYS-196 did not rename it — it is not a club/mix
    # identifier column, just a notice-sent timestamp).
    empty_round_notice_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
