import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthIdentity(Base):
    """A third-party sign-in identity linked to an MMC account
    (MysteryMixClub-4vii.9).

    Generalizes what `User.google_id` used to do alone, so Sign in with Apple
    (Guideline 4.8) and Google Sign-In share one lookup/link/conflict path
    instead of duplicating it per provider. ``provider`` + ``subject`` is the
    provider's own stable identifier for the account -- Google's `sub` claim,
    Apple's `sub` claim -- never the email, since a person can change their
    email with either provider but never their subject. Unique on
    (provider, subject): the same third-party account can never be linked to
    two different MMC users at once, which is the core invariant every
    resolve/link routine in app/api/routes/auth.py depends on.

    `User.google_id` is left in place (read-only going forward, migration
    0001 backfills it into this table) rather than dropped in the same
    change that starts relying on this table -- dropping a column outright
    is not an additive migration, and MMC is live in prod (a half-migrated
    read path is more dangerous here than one unused legacy column).
    """

    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_auth_identities_provider_subject"),
        CheckConstraint("provider IN ('google', 'apple')", name="ck_auth_identities_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # "google" | "apple", CHECK-constrained below (same plain-string +
    # CHECK pattern as Report.content_type) rather than a DB enum -- a Postgres
    # enum needs its own ALTER TYPE migration to extend, a CHECK constraint
    # migration is no smaller, and a plain string keeps this model's own type
    # simple.
    provider: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
