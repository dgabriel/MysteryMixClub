import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.db.base import Base


class Note(Base):
    __tablename__ = "notes"
    # No unique constraint: a player may leave multiple notes on a submission
    # (free-form appreciation). The 280-char limit is enforced at the API layer,
    # mirroring how submissions.note is handled (technical-design §6).

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # DB column is mix_id (MYS-196); attr name stays until R3/R4 cleanup.
    round_id: Mapped[uuid.UUID] = mapped_column(
        "mix_id", UUID(as_uuid=True), ForeignKey("mixes.id"), nullable=False, index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # New-vocabulary synonym (MYS-196 seam): both names work as attrs and
    # constructor kwargs until the R3/R4 cleanup makes the new name primary.
    mix_id = synonym("round_id")
