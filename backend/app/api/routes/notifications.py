"""Email-notification endpoints (MYS-109).

Just the one-click unsubscribe landing today. It's deliberately unauthenticated:
the link is opened from an email with no bearer token, so the recipient's
identity rides in a signed, non-expiring token (``app.auth.jwt`` ``unsubscribe``
purpose). Toggling the flag here is the only thing the token authorizes.
"""

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import JWTError, decode_unsubscribe_token
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _page(message: str) -> HTMLResponse:
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>MysteryMixClub</title></head>"
        "<body style='font-family:monospace;background:#F0EDE6;color:#2E2B27;"
        "display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0'>"
        f"<p style='max-width:32rem;padding:24px;text-align:center'>{message}</p>"
        "</body></html>"
    )
    return HTMLResponse(content=html)


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(token: str, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    """Turn off email notifications for the user named in a signed token.

    Idempotent and forgiving: a valid token always lands on the confirmation
    page (even if already unsubscribed); an invalid/forged token gets a calm
    error page rather than a stack trace. Always 200 so mail clients that
    pre-fetch links don't flag it."""
    try:
        user_id: uuid.UUID = decode_unsubscribe_token(token)
    except JWTError:
        return _page("That unsubscribe link didn't work. Try the link from a more recent email.")

    await db.execute(update(User).where(User.id == user_id).values(email_notifications=False))
    await db.commit()
    return _page(
        "You're unsubscribed from MysteryMixClub mystery mix emails. "
        "You can turn them back on anytime in your account settings."
    )
