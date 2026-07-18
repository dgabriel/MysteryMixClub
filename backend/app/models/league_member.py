import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.db.base import Base


class LeagueMember(Base):
    # DB uses club/mix vocabulary (MYS-196 cutover); Python attr names stay old
    # until the R3/R4 identifier cleanup — mapped_column("new_name") is the seam.
    __tablename__ = "club_members"
    __table_args__ = (
        UniqueConstraint("club_id", "user_id", name="uq_club_members_club_user"),
        CheckConstraint("role IN ('member', 'admin')", name="ck_league_members_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    league_id: Mapped[uuid.UUID] = mapped_column(
        "club_id", UUID(as_uuid=True), ForeignKey("clubs.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # Per-league participation default for this member (MYS-112), seeded from
    # leagues.default_vibe_mode at join and toggleable anytime. A round's
    # submission.participation_mode overrides it for that round.
    vibe_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Co-organizer support (MYS-99): "admin" grants full operational parity with
    # the league's fixed organizer_id everywhere _load_league_as_organizer gates.
    # The organizer's own row is never toggled here — see leagues.py's role
    # endpoint, which rejects changing organizer_id's row directly.
    role: Mapped[str] = mapped_column(
        Text, nullable=False, default="member", server_default=text("'member'")
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # New-vocabulary synonym (MYS-196 seam): both names work as attrs and
    # constructor kwargs until the R3/R4 cleanup makes the new name primary.
    club_id = synonym("league_id")
