import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Vote(Base):
    __tablename__ = "votes"
    # One row per (voter, submission) — a player who spends several of their
    # votes on one song gets a heavier row, not more rows (ADR 0014). The unique
    # constraint therefore survives weighted voting unchanged; it is `weight`
    # that carries "how many", not the row count.
    __table_args__ = (
        UniqueConstraint("voter_id", "submission_id", name="uq_votes_voter_submission"),
        CheckConstraint("weight >= 1", name="ck_votes_weight_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mix_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mixes.id"), nullable=False, index=True
    )
    voter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False, index=True
    )
    # How many of the voter's allowance sit on this song. Never 0 — withdrawing
    # a vote deletes the row. Server default 1 so pre-ADR-0014 rows migrate for
    # free and any writer that ignores the column still produces a normal vote.
    weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
