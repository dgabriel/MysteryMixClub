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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ClubMember(Base):
    # Renamed from LeagueMember (MYS-195, R3/R4 identifier cleanup) — the DB was
    # already renamed to club/mix vocabulary in MYS-196, so the attribute names
    # now match the column names directly with no seam. The role check
    # constraint is renamed to match (see migrations/versions for the
    # accompanying metadata-only rename).
    __tablename__ = "club_members"
    __table_args__ = (
        UniqueConstraint("club_id", "user_id", name="uq_club_members_club_user"),
        CheckConstraint("role IN ('member', 'admin')", name="ck_club_members_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # Per-club participation default for this member (MYS-112), seeded from
    # clubs.default_vibe_mode at join and toggleable anytime. A mix's
    # submission.participation_mode overrides it for that mix.
    vibe_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Co-organizer support (MYS-99): "admin" grants full operational parity with
    # the club's fixed organizer_id everywhere _load_club_as_organizer gates.
    # The organizer's own row is never toggled here — see clubs.py's role
    # endpoint, which rejects changing organizer_id's row directly.
    role: Mapped[str] = mapped_column(
        Text, nullable=False, default="member", server_default=text("'member'")
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
