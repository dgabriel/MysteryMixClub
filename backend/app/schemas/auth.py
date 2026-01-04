from pydantic import BaseModel, EmailStr
from app.schemas.user import UserResponse


class LoginRequest(BaseModel):
    """Schema for login requests"""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Schema for token responses"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    """Schema for login responses"""
    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
