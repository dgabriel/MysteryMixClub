from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import generate_token, hash_token
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.magic_link_token import MagicLinkToken
from app.services.email import EmailSender, get_email_sender

router = APIRouter(prefix="/auth", tags=["auth"])

_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW = timedelta(hours=1)
_TOKEN_TTL = timedelta(minutes=15)

_NEUTRAL_MESSAGE = "If that email is registered, a sign-in link is on its way."


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkResponse(BaseModel):
    message: str = _NEUTRAL_MESSAGE


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
