from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserBase(BaseModel):
    """Base schema for user data"""
    email: EmailStr
    name: str


class UserCreate(UserBase):
    """Schema for creating a new user"""
    password: str


class UserUpdate(BaseModel):
    """Schema for updating user data"""
    name: Optional[str] = None
    avatar_url: Optional[str] = None


class UserResponse(UserBase):
    """Schema for user responses"""
    id: int
    avatar_url: Optional[str] = None
    is_super_user: bool
    is_active: bool
    created_at: datetime
    tidal_connected: bool = False

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_tidal(cls, user):
        """Create response with tidal_connected computed from tidal_user_id"""
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            avatar_url=user.avatar_url,
            is_super_user=user.is_super_user,
            is_active=user.is_active,
            created_at=user.created_at,
            tidal_connected=user.tidal_user_id is not None,
        )
