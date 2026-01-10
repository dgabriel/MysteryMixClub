from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime


# League Member schemas
class LeagueMemberBase(BaseModel):
    user_id: int
    is_admin: bool = False


class LeagueMemberCreate(LeagueMemberBase):
    league_id: int


class LeagueMemberResponse(LeagueMemberBase):
    id: int
    league_id: int
    joined_at: datetime
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


# League schemas
class LeagueBase(BaseModel):
    name: str
    description: Optional[str] = None
    songs_per_round: int = Field(default=1, ge=1, le=5)


class LeagueCreate(LeagueBase):
    pass


class LeagueUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    songs_per_round: Optional[int] = Field(None, ge=1, le=5)


class LeagueResponse(LeagueBase):
    id: int
    invite_code: str
    created_by_id: int
    created_at: datetime
    member_count: Optional[int] = None
    is_member: Optional[bool] = None
    is_admin: Optional[bool] = None
    
    model_config = ConfigDict(from_attributes=True)


class LeagueDetailResponse(LeagueResponse):
    members: List[LeagueMemberResponse] = []
    
    model_config = ConfigDict(from_attributes=True)


class JoinLeagueRequest(BaseModel):
    invite_code: str
