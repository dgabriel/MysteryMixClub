from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Song(Base):
    __tablename__ = "songs"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False)

    # Song metadata
    song_title = Column(String(200), nullable=False)
    artist_name = Column(String(200), nullable=False)
    album_name = Column(String(200), nullable=True)

    # Links from song.link API
    songlink_url = Column(String(500), nullable=False)  # Universal link
    spotify_url = Column(String(500), nullable=True)
    apple_music_url = Column(String(500), nullable=True)
    youtube_url = Column(String(500), nullable=True)
    amazon_music_url = Column(String(500), nullable=True)
    tidal_url = Column(String(500), nullable=True)
    youtube_music_url = Column(String(500), nullable=True)
    deezer_url = Column(String(500), nullable=True)

    # Artwork
    artwork_url = Column(String(500), nullable=True)

    # Order within submission (1-5)
    order = Column(Integer, nullable=False, default=1)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    submission = relationship("Submission", back_populates="songs")
    votes = relationship("Vote", back_populates="song", cascade="all, delete-orphan")
