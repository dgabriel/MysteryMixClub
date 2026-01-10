from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class SongBase(BaseModel):
    song_title: str
    artist_name: str
    album_name: Optional[str] = None


class SongCreate(SongBase):
    songlink_url: str
    spotify_url: Optional[str] = None
    apple_music_url: Optional[str] = None
    youtube_url: Optional[str] = None
    amazon_music_url: Optional[str] = None
    tidal_url: Optional[str] = None
    youtube_music_url: Optional[str] = None
    deezer_url: Optional[str] = None
    artwork_url: Optional[str] = None
    order: int = 1


class SongResponse(SongBase):
    id: int
    submission_id: int
    songlink_url: str
    spotify_url: Optional[str] = None
    apple_music_url: Optional[str] = None
    youtube_url: Optional[str] = None
    amazon_music_url: Optional[str] = None
    tidal_url: Optional[str] = None
    youtube_music_url: Optional[str] = None
    deezer_url: Optional[str] = None
    artwork_url: Optional[str] = None
    order: int
    created_at: datetime

    # Vote aggregation (can be added after voting calculations)
    vote_count: Optional[int] = None
    average_rank: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class MusicSearchRequest(BaseModel):
    artist: str
    title: str
    album: Optional[str] = None


class MusicSearchResponse(BaseModel):
    songlink_url: str
    song_title: Optional[str] = None
    artist_name: Optional[str] = None
    album_name: Optional[str] = None
    artwork_url: Optional[str] = None
    spotify_url: Optional[str] = None
    apple_music_url: Optional[str] = None
    youtube_url: Optional[str] = None
    amazon_music_url: Optional[str] = None
    tidal_url: Optional[str] = None
    youtube_music_url: Optional[str] = None
    deezer_url: Optional[str] = None
