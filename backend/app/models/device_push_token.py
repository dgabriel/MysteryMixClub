import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DevicePushToken(Base):
    """A device registered to receive push notifications
    (MysteryMixClub-4vii.25, IOS-04).

    One row per *device*, not per user: a user signed in on two devices has
    two rows, and both get every push. ``device_token`` is the APNs token
    itself and is globally unique -- registering a token that already exists
    reassigns it to the current user (the pattern on a shared/reset device,
    or simply signing out and back in as someone else on the same phone)
    rather than erroring or creating a duplicate live registration for a
    token that can only ever be delivered to one app install.

    ``platform`` is CHECK-constrained to ``'ios'`` only today (same plain-
    string + CHECK pattern as ``AuthIdentity.provider`` and
    ``Report.content_type`` -- a CHECK migration to add a value is no smaller
    than a DB enum's, so there's no reason to reach for one), kept as a real
    column rather than assumed so a future Android build doesn't need a
    schema change, just a wider CHECK.
    """

    __tablename__ = "device_push_tokens"
    __table_args__ = (
        CheckConstraint("platform IN ('ios')", name="ck_device_push_tokens_platform"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # The login session this registration was made under (MysteryMixClub-4vii.36).
    # Logout invalidates the session and deletes its rows in one transaction, and
    # a registration is only accepted from a live session, so a POST that lands
    # after logout cannot recreate a row. NULL for a registration made with a
    # token that carried no session (issued before the claim existed) or whose
    # session row has since been deleted; SET NULL rather than CASCADE so purging
    # an old session never silently removes a device that is still registered.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    device_token: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    platform: Mapped[str] = mapped_column(String, nullable=False, default="ios")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
