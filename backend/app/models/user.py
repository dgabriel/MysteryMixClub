from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class User(Base):
    """User model representing application users"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    name = Column(String(100), nullable=False)
    avatar_url = Column(String(500), nullable=True)
    is_super_user = Column(Boolean, default=False, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Tidal OAuth (beta - unofficial API)
    tidal_user_id = Column(String(100), nullable=True)
    tidal_session_data = Column(Text, nullable=True)

    # Relationships
    created_leagues = relationship("League", back_populates="created_by")
    league_memberships = relationship("LeagueMember", back_populates="user")
    submissions = relationship("Submission", back_populates="user")
    votes = relationship("Vote", foreign_keys="Vote.voter_id", back_populates="voter")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, name={self.name})>"
