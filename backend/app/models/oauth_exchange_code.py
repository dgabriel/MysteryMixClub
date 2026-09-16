import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OAuthExchangeCode(Base):
    """A one-time code handed to the native iOS app after a provider OAuth
    round-trip completes inside an ASWebAuthenticationSession
    (MysteryMixClub-4vii.21).

    Universal Links can't close this loop reliably: Google's own login screen
    can take long enough (password, 2FA) that iOS evicts the app from memory
    in the background, and Capacitor's `appUrlOpen` event is known to not
    fire on a cold start via Universal Link (ionic-team/capacitor#6662).
    ASWebAuthenticationSession keeps the app alive and foregrounded for the
    whole flow instead, but its completion callback is only a captured URL --
    there's no cookie jar shared with the app's own WKWebView to rely on. So
    the callback mints this instead of setting the session cookie directly,
    and the app's own JS exchanges it for a real session via a normal fetch
    from its own WebView (POST /auth/google/native-exchange) -- the same
    "land on a URL carrying a one-time code, then fetch to redeem it"
    shape magic-link verification already uses successfully.

    Same single-use pattern as MagicLinkToken: hard-deleted on lookup,
    whether valid or expired.
    """

    __tablename__ = "oauth_exchange_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
