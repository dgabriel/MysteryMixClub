from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from app.models.round import RoundStatus


class RoundBase(BaseModel):
    theme: str
    description: Optional[str] = None


class RoundCreate(RoundBase):
    league_id: int
    order: Optional[int] = None  # Optional, defaults to last position


class RoundUpdate(BaseModel):
    theme: Optional[str] = None
    description: Optional[str] = None
    # Note: deadlines are auto-calculated, not editable
    # Status changes should use dedicated endpoints (start, complete)


class RoundResponse(RoundBase):
    id: int
    league_id: int
    order: int
    status: RoundStatus

    # Timestamps (nullable until round starts)
    started_at: Optional[datetime] = None
    submission_deadline: Optional[datetime] = None
    voting_started_at: Optional[datetime] = None
    voting_deadline: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    created_at: datetime
    submission_count: Optional[int] = None
    user_has_submitted: Optional[bool] = None
    is_admin: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)


class SubmissionBase(BaseModel):
    song_title: str
    artist_name: str
    album_name: Optional[str] = None
    songlink_url: str
    spotify_url: Optional[str] = None
    apple_music_url: Optional[str] = None
    youtube_url: Optional[str] = None
    artwork_url: Optional[str] = None


class SubmissionCreate(SubmissionBase):
    round_id: int


class SubmissionUpdate(BaseModel):
    song_title: Optional[str] = None
    artist_name: Optional[str] = None
    album_name: Optional[str] = None
    songlink_url: Optional[str] = None
    spotify_url: Optional[str] = None
    apple_music_url: Optional[str] = None
    youtube_url: Optional[str] = None
    artwork_url: Optional[str] = None


class SubmissionResponse(SubmissionBase):
    id: int
    round_id: int
    user_id: int
    submitted_at: datetime
    user_name: Optional[str] = None  # Only shown after voting
    
    model_config = ConfigDict(from_attributes=True)


class RoundDetailResponse(RoundResponse):
    submissions: List[SubmissionResponse] = []
    
    model_config = ConfigDict(from_attributes=True)
