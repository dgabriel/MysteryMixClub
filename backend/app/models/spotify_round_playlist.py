import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.db.base import Base


class SpotifyRoundPlaylist(Base):
    # DB uses club/mix vocabulary (MYS-196 cutover); Python attr names stay old
    # until the R3/R4 identifier cleanup — mapped_column("new_name") is the seam.
    __tablename__ = "spotify_mix_playlists"
    __table_args__ = (
        UniqueConstraint("mix_id", "user_id", name="uq_spotify_mix_playlists_mix_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        "mix_id", UUID(as_uuid=True), ForeignKey("mixes.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    playlist_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # New-vocabulary synonym (MYS-196 seam): both names work as attrs and
    # constructor kwargs until the R3/R4 cleanup makes the new name primary.
    mix_id = synonym("round_id")
