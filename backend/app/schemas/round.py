from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from app.models.round import RoundStatus
from app.schemas.song import SongCreate, SongResponse


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
    league_name: Optional[str] = None
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
    user_has_voted: Optional[bool] = None
    is_admin: Optional[bool] = None
    songs_per_round: Optional[int] = None  # From league settings

    model_config = ConfigDict(from_attributes=True)


class SubmissionCreate(BaseModel):
    round_id: int
    songs: List[SongCreate]


class SubmissionResponse(BaseModel):
    id: int
    round_id: int
    user_id: int
    submitted_at: datetime
    songs: List[SongResponse] = []
    user_name: Optional[str] = None  # Only shown after voting

    model_config = ConfigDict(from_attributes=True)


class RoundDetailResponse(RoundResponse):
    submissions: List[SubmissionResponse] = []
    
    model_config = ConfigDict(from_attributes=True)
