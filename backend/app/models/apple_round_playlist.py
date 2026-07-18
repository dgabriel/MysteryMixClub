import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppleRoundPlaylist(Base):
    """One Apple Music library playlist per (round, user) — MYS-108.

    Unlike its Spotify counterpart, which keys every row to one shared account,
    Apple playlists are genuinely per-player: MYS-107 established that library
    playlists can't be made public, so each member generates their own copy into
    their own library. Stores only the playlist id (not a credential) so the
    round page can surface a link on later visits.
    """

    __tablename__ = "apple_round_playlists"
    __table_args__ = (
        UniqueConstraint("round_id", "user_id", name="uq_apple_round_playlists_round_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rounds.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    playlist_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Set when a rollback reopens the round (MYS-168): the playlist in the
    # member's library no longer reflects the round's submissions. The row is
    # kept rather than deleted so a rebuild knows it is a *revision* and can
    # name itself distinctly — Apple happily accepts two identically-named
    # playlists, which is confusing in the member's library.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
