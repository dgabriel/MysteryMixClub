from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import JWTError, decode_access_token
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.user import User

# Neutral 401 detail for every failure mode so the caller can't tell a missing
# header from a bad token from a deleted user (TD 5).
_UNAUTHENTICATED_MESSAGE = "not authenticated"

# auto_error=False so a missing/invalid Authorization header yields our 401
# rather than HTTPBearer's default 403.
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user from a Bearer access token.

    Raises 401 for a missing/malformed header, an invalid or expired token, or
    a user that does not exist or has been soft-deleted.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_UNAUTHENTICATED_MESSAGE,
        )

    try:
        user_id = decode_access_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_UNAUTHENTICATED_MESSAGE,
        ) from exc

    user = await db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_UNAUTHENTICATED_MESSAGE,
        )

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Best-effort identity for routes usable by both anonymous and signed-in
    callers (e.g. invite preview, MYS-181). Same resolution as
    get_current_user, but a missing/invalid/expired token or unknown user
    resolves to None instead of raising."""
    if credentials is None:
        return None
    try:
        user_id = decode_access_token(credentials.credentials)
    except JWTError:
        return None
    return await db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))


async def get_platform_admin(
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> User:
    """Require the caller to be a platform admin (an email in SEED_ADMIN_EMAILS).

    Builds on get_current_user, so a missing/invalid token still yields 401;
    an authenticated non-admin gets 403 (MYS-128).
    """
    if current_user.email.lower() not in settings.seed_admin_email_set:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not authorized",
        )
    return current_user
