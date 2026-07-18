import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.db.base import Base


class AppleRoundPlaylist(Base):
    """One Apple Music library playlist per (round, user) — MYS-108.

    Unlike its Spotify counterpart, which keys every row to one shared account,
    Apple playlists are genuinely per-player: MYS-107 established that library
    playlists can't be made public, so each member generates their own copy into
    their own library. Stores only the playlist id (not a credential) so the
    round page can surface a link on later visits.
    """

    # DB uses club/mix vocabulary (MYS-196 cutover); Python attr names stay old
    # until the R3/R4 identifier cleanup — mapped_column("new_name") is the seam.
    __tablename__ = "apple_mix_playlists"
    __table_args__ = (
        UniqueConstraint("mix_id", "user_id", name="uq_apple_mix_playlists_mix_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        "mix_id", UUID(as_uuid=True), ForeignKey("mixes.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    playlist_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # The name as created in Apple, shown so a member can find the playlist in
    # their library (MYS-190) — iOS can't deep-link to a library playlist, so
    # naming it is the only way to point at it. Stored rather than recomputed
    # because a revision's "[revised on HH:MM]" suffix is a wall-clock time.
    # Nullable: rows created before MYS-190 have no recorded name.
    playlist_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Set when a rollback reopens the round (MYS-168): the playlist in the
    # member's library no longer reflects the round's submissions. The row is
    # kept rather than deleted so a rebuild knows it is a *revision* and can
    # name itself distinctly — Apple happily accepts two identically-named
    # playlists, which is confusing in the member's library.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # New-vocabulary synonym (MYS-196 seam): both names work as attrs and
    # constructor kwargs until the R3/R4 cleanup makes the new name primary.
    mix_id = synonym("round_id")
