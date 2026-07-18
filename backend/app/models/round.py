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
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.db.base import Base

# Round lifecycle states (technical-design §6). Forward-only:
# pending -> open_submission -> open_voting -> closed.
ROUND_STATES = ("pending", "open_submission", "open_voting", "closed")


class Round(Base):
    # DB is renamed to mix vocabulary (MYS-196 cutover); Python attrs keep the
    # old names until R3/R4 cleanup. The mapped_column("new_name") pins are the
    # seam. UniqueConstraint references DB column names, so it uses the new ones.
    __tablename__ = "mixes"
    # A club's mix numbers are unique and sequential.
    __table_args__ = (UniqueConstraint("club_id", "mix_number", name="uq_mixes_club_number"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    league_id: Mapped[uuid.UUID] = mapped_column(
        "club_id", UUID(as_uuid=True), ForeignKey("clubs.id"), nullable=False, index=True
    )
    round_number: Mapped[int] = mapped_column("mix_number", Integer, nullable=False)
    # Nullable: rounds are auto-generated at league creation without a theme;
    # the organizer fills it in while the round is still pending (MYS-62).
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
    # When the round entered open_submission (MYS-69). Auto-advance scopes its
    # quorum to members present at this moment; nullable because pending rounds
    # have not opened yet.
    submission_opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Deadline-notification bookkeeping (MYS-159). The deadline cron (MYS-145)
    # stamps each of these the one time it sends the corresponding notice, so a
    # warning / empty-round notice fires exactly once per round. Nullable: unset
    # until (and unless) that notice goes out.
    submission_warning_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voting_warning_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    empty_round_notice_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # New-vocabulary synonym (MYS-196 seam): both names work as attrs and
    # constructor kwargs until the R3/R4 cleanup makes the new name primary.
    club_id = synonym("league_id")
    mix_number = synonym("round_number")
