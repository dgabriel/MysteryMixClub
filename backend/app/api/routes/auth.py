from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.auth.tokens import generate_token, hash_token
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.magic_link_token import MagicLinkToken
from app.models.session import Session
from app.models.user import User
from app.services.email import EmailSender, get_email_sender

router = APIRouter(prefix="/auth", tags=["auth"])

_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW = timedelta(hours=1)
_TOKEN_TTL = timedelta(minutes=15)

_REFRESH_COOKIE_NAME = "refresh_token"
_REFRESH_COOKIE_PATH = "/api/v1/auth"
_REFRESH_TOKEN_MAX_AGE = int(timedelta(days=30).total_seconds())
_DEVICE_HINT_MAX_LENGTH = 255

_NEUTRAL_MESSAGE = "If that email is registered, a sign-in link is on its way."
_INVALID_LINK_MESSAGE = "invalid or expired link"


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkResponse(BaseModel):
    message: str = _NEUTRAL_MESSAGE


class VerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/request", response_model=MagicLinkResponse)
async def request_magic_link(
    payload: MagicLinkRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_sender: EmailSender = Depends(get_email_sender),
) -> MagicLinkResponse:
    email = payload.email.lower()
    now = datetime.now(timezone.utc)

    recent_count = await db.scalar(
        select(func.count())
        .select_from(MagicLinkToken)
        .where(
            MagicLinkToken.email == email,
            MagicLinkToken.created_at > now - _RATE_LIMIT_WINDOW,
        )
    )
    if (recent_count or 0) >= _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in requests. Please try again later.",
        )

    raw_token = generate_token()
    db.add(
        MagicLinkToken(
            email=email,
            token_hash=hash_token(raw_token),
            expires_at=now + _TOKEN_TTL,
            used=False,
        )
    )
    await db.commit()

    link = f"{settings.app_base_url.rstrip('/')}/auth/verify?token={raw_token}"
    email_sender.send_magic_link(email, link)

    return MagicLinkResponse()


@router.get("/verify", response_model=VerifyResponse)
async def verify_magic_link(
    token: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user_agent: str | None = Header(default=None),
) -> VerifyResponse:
    now = datetime.now(timezone.utc)

    token_row = await db.scalar(
        select(MagicLinkToken).where(MagicLinkToken.token_hash == hash_token(token))
    )

    # Single-use enforcement: any matching token is hard-deleted on lookup,
    # whether it was valid or already expired (TD 5).
    if token_row is not None:
        await db.delete(token_row)

    if token_row is None or token_row.expires_at <= now:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_LINK_MESSAGE,
        )

    email = token_row.email

    user = await db.scalar(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    if user is None:
        user = User(email=email, display_name="", default_vibe_mode=False)
        db.add(user)
        await db.flush()

    raw_refresh_token = generate_token()
    device_hint = user_agent[:_DEVICE_HINT_MAX_LENGTH] if user_agent else None
    db.add(
        Session(
            user_id=user.id,
            refresh_token_hash=hash_token(raw_refresh_token),
            device_hint=device_hint,
            created_at=now,
            last_used_at=now,
            invalidated_at=None,
        )
    )

    access_token = create_access_token(user.id)

    await db.commit()

    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        max_age=_REFRESH_TOKEN_MAX_AGE,
        path=_REFRESH_COOKIE_PATH,
        httponly=True,
        samesite="strict",
        secure=(settings.environment == "production"),
    )

    return VerifyResponse(access_token=access_token)
