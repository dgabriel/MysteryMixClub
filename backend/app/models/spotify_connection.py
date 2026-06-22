import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SpotifyConnection(Base):
    """A user's authorized Spotify account, for creating playlists in their
    library (MYS-83).

    One connection per user (``uq_spotify_connections_user``); re-authorizing
    replaces it in place. Unlike the app's own sessions (which store a *hash* of
    a token we only ever need to verify), Spotify's refresh token must be
    *replayed* to mint new access tokens, so it is stored **encrypted at rest**
    (reversible) rather than hashed — see :mod:`app.services.spotify_token_crypto`.
    The client never sees it.
    """

    __tablename__ = "spotify_connections"
    __table_args__ = (UniqueConstraint("user_id", name="uq_spotify_connections_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # The connected Spotify account's own user id (the playlist owner).
    spotify_user_id: Mapped[str] = mapped_column(String, nullable=False)
    # Fernet-encrypted Spotify refresh token. Decrypted server-side only.
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # Space-separated scopes granted at consent time, for diagnostics / re-consent.
    scope: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
