from pydantic import BaseModel, ConfigDict, field_validator
from typing import List
from datetime import datetime


class VoteCreate(BaseModel):
    """Schema for creating votes - user submits ranked list of song IDs"""
    round_id: int
    # List of song IDs in ranked order [1st place, 2nd place, 3rd place]
    ranked_songs: List[int]

    @field_validator('ranked_songs')
    @classmethod
    def validate_ranked_songs(cls, v):
        if len(v) < 1 or len(v) > 3:
            raise ValueError('Must rank 1-3 songs')
        if len(v) != len(set(v)):
            raise ValueError('Cannot vote for the same song multiple times')
        return v


class VoteUpdate(BaseModel):
    """Schema for updating votes"""
    ranked_songs: List[int]

    @field_validator('ranked_songs')
    @classmethod
    def validate_ranked_songs(cls, v):
        if len(v) < 1 or len(v) > 3:
            raise ValueError('Must rank 1-3 songs')
        if len(v) != len(set(v)):
            raise ValueError('Cannot vote for the same song multiple times')
        return v


class VoteResponse(BaseModel):
    """Schema for vote response"""
    id: int
    round_id: int
    voter_id: int
    song_id: int
    rank: int
    voted_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserVotesResponse(BaseModel):
    """Schema for user's votes in a round"""
    round_id: int
    ranked_songs: List[int]  # List of song IDs in ranked order
    voted_at: datetime
