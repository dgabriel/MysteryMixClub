import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SpotifyMixPlaylist(Base):
    # Renamed from SpotifyRoundPlaylist (MYS-195, R3/R4 identifier cleanup) —
    # the DB was already renamed to club/mix vocabulary in MYS-196, so the
    # attribute names now match the column names directly with no seam.
    __tablename__ = "spotify_mix_playlists"
    __table_args__ = (
        UniqueConstraint("mix_id", "user_id", name="uq_spotify_mix_playlists_mix_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mix_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mixes.id"), nullable=False, index=True
    )
    # `user_id` here is the connected account used to generate the club's
    # (shared) Spotify playlist, not a per-viewer row -- see
    # spotify_playlist_generation.py. ON DELETE CASCADE (MysteryMixClub-4vii.38):
    # that account is admin-managed, not a member's own self-service account,
    # so deleting it is a deliberate action and losing this row along with it
    # is an accepted, understood consequence, not a surprise.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    playlist_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
