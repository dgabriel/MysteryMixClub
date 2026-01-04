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

    class Config:
        from_attributes = True
