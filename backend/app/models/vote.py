import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.db.base import Base


class Vote(Base):
    __tablename__ = "votes"
    # A voter may vote for a given submission at most once (technical-design §6).
    __table_args__ = (
        UniqueConstraint("voter_id", "submission_id", name="uq_votes_voter_submission"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # DB column is mix_id (MYS-196); attr name stays until R3/R4 cleanup.
    round_id: Mapped[uuid.UUID] = mapped_column(
        "mix_id", UUID(as_uuid=True), ForeignKey("mixes.id"), nullable=False, index=True
    )
    voter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # New-vocabulary synonym (MYS-196 seam): both names work as attrs and
    # constructor kwargs until the R3/R4 cleanup makes the new name primary.
    mix_id = synonym("round_id")
