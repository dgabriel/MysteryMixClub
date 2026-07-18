import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.db.base import Base


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Null marks a platform invite (MYS-182): grants signup only, no league
    # attachment. Non-null is a normal per-league shareable invite.
    # DB column is club_id (MYS-196); attr name stays until R3/R4 cleanup.
    league_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        "club_id", UUID(as_uuid=True), ForeignKey("clubs.id"), nullable=True, index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    token: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    # Always None in v1: invites are shareable links with no expiry (TD 6).
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Set when a platform (league-less) invite is consumed by a new signup —
    # makes it single-use. Never set for a league invite, which stays
    # multi-use (MYS-182 follow-up).
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Who consumed it (paired with used_at). Lets the preview endpoint tell
    # "the same visitor checking again" from "someone else hitting a dead
    # link" — mirrors the already-member bypass a league invite gets.
    used_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # New-vocabulary synonym (MYS-196 seam): both names work as attrs and
    # constructor kwargs until the R3/R4 cleanup makes the new name primary.
    club_id = synonym("league_id")
