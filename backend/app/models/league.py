import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Nullable: hard-purging an account (MYS-50) nulls the organizer of any
    # completed leagues it organized, preserving other members' history.
    organizer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    total_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    votes_per_player: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )
    # Admin-set cap on how many songs a player may submit per round (MYS-116).
    # Chosen once at league setup and applied to every round; 1..5, default 1
    # (one song = today's behavior). Enforced in the submission endpoint.
    songs_per_submission: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    current_round: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    state: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default=text("'active'")
    )
    # Deadline windows (in days) for the league's rounds (MYS-159). A round closes
    # on quorum OR its deadline, whichever comes first (epic MYS-158); when a round
    # opens, these seed its submission_deadline / voting_deadline. Organizer-set,
    # 1..14, default 3.
    submission_deadline_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )
    voting_deadline_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )
    # Admin-set default participation mode for the league (MYS-112). Seeds each
    # member's league_members.vibe_mode at join; per-round overrides live on the
    # submission's participation_mode.
    default_vibe_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
