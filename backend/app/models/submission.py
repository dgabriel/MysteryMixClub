import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# A submission's participation mode (technical-design §6 / personas §4).
PARTICIPATION_MODES = ("playing", "vibing")


class Submission(Base):
    __tablename__ = "submissions"
    # One submission per player per round (replace-in-place while the round is open).
    __table_args__ = (UniqueConstraint("round_id", "user_id", name="uq_submissions_round_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rounds.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    isrc: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    artist: Mapped[str] = mapped_column(String, nullable=False)
    album: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    album_art_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Assembled cross-service links {platform: url} for playback (best-effort).
    platform_links: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    # Cached YouTube video id for the round playlist link (MYS-78). The stored
    # YouTube platform_link is only a search deep-link with no video id, so this
    # is resolved via the YouTube Data API at submit time (and lazily backfilled
    # at playlist time for pre-existing rows), then cached to avoid repeat calls.
    youtube_video_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Cached Spotify track URI (spotify:track:...) resolved from the ISRC via the
    # Spotify search API, for building a saved playlist (MYS-83). Resolved lazily
    # at playlist-create time and cached; nullable when no match is found.
    spotify_track_uri: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    participation_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="playing", server_default=text("'playing'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
