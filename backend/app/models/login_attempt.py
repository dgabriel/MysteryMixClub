import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LoginAttempt(Base):
    """One row per FAILED password login, for brute-force rate limiting
    (ADR 0007). Successful logins delete the email's rows, so only sustained
    failure trips the limit.

    Counting rows in a time window is the same mechanism ``/auth/request``
    already uses against ``magic_link_tokens``; password login needs its own
    table because there's no token row to count.
    """

    __tablename__ = "login_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Composite, not email-only: every read is "this email, inside the window",
    # so created_at has to be in the index or a targeted address's whole history
    # gets scanned before the time filter is applied. Leading on email means it
    # still serves the delete-by-email on successful login and account purge.
    __table_args__ = (Index("ix_login_attempts_email_created_at", "email", "created_at"),)
