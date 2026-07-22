import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WaitlistEntry(Base):
    """A public join-the-waitlist request (MYS-215, temporary pre-launch flow).

    Not a user account and not an invite — just a request to be sent one.
    An admin turns a row into an actual signup by minting a platform invite
    (the same club-less kind POST /admin/invites already creates) and
    emailing it, which stamps invited_at/invited_by. Resendable: inviting an
    already-invited row is allowed (mints a fresh invite, re-stamps both
    fields), since the 48h invite link may have expired unused.
    """

    __tablename__ = "waitlist_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Always lowercased before storage/lookup (matches the auth.py convention
    # for email normalization) so the unique constraint catches real dupes.
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    invited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
