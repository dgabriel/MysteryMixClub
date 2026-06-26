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
    current_round: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    state: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default=text("'active'")
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
