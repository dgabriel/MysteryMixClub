from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class RoundStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"


class Round(Base):
    __tablename__ = "rounds"

    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    theme = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    order = Column(Integer, nullable=False, default=0)  # Order in the queue
    status = Column(Enum(RoundStatus, values_callable=lambda obj: [e.value for e in obj]), default=RoundStatus.PENDING, nullable=False, index=True)

    # Timestamps for round progression
    started_at = Column(DateTime(timezone=True), nullable=True)
    submission_deadline = Column(DateTime(timezone=True), nullable=True)
    voting_started_at = Column(DateTime(timezone=True), nullable=True)
    voting_deadline = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    league = relationship("League", back_populates="rounds")
    submissions = relationship("Submission", back_populates="round", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="round", cascade="all, delete-orphan")


class Submission(Base):
    __tablename__ = "submissions"
    
    id = Column(Integer, primary_key=True, index=True)
    round_id = Column(Integer, ForeignKey("rounds.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Song metadata from Songlink/Odesli
    song_title = Column(String(200), nullable=False)
    artist_name = Column(String(200), nullable=False)
    album_name = Column(String(200), nullable=True)
    songlink_url = Column(String(500), nullable=False)  # Universal link
    spotify_url = Column(String(500), nullable=True)
    apple_music_url = Column(String(500), nullable=True)
    youtube_url = Column(String(500), nullable=True)
    artwork_url = Column(String(500), nullable=True)
    
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    round = relationship("Round", back_populates="submissions")
    user = relationship("User", back_populates="submissions")
    votes = relationship("Vote", back_populates="submission", cascade="all, delete-orphan")


class Vote(Base):
    __tablename__ = "votes"

    id = Column(Integer, primary_key=True, index=True)
    round_id = Column(Integer, ForeignKey("rounds.id"), nullable=False)
    voter_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False)
    rank = Column(Integer, nullable=False)  # 1 = 1st place, 2 = 2nd place, 3 = 3rd place

    voted_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    round = relationship("Round", back_populates="votes")
    voter = relationship("User", foreign_keys=[voter_id], back_populates="votes")
    submission = relationship("Submission", back_populates="votes")
