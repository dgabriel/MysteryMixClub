"""Public waitlist (MYS-215, temporary pre-launch access-request flow).

Stands in for "email us for an invite" on the login page while
``settings.waitlist_enabled`` is on. A waitlist row is not an invite and not
a user — it only becomes a real signup when an admin acts on it
(``POST /admin/waitlist/{id}/invite``, in ``admin.py``), which mints the same
club-less platform invite ``POST /admin/invites`` already creates and emails
it. The existing club-invite and platform-invite flows are untouched.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import EmailStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.wire import WireModel
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.waitlist_entry import WaitlistEntry

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


class WaitlistStatusResponse(WireModel):
    enabled: bool


class WaitlistJoinRequest(WireModel):
    email: EmailStr


class WaitlistEntryResponse(WireModel):
    id: str
    email: str
    created_at: datetime


@router.get("/enabled", response_model=WaitlistStatusResponse)
async def get_waitlist_enabled(
    settings: Settings = Depends(get_settings),
) -> WaitlistStatusResponse:
    """Whether the frontend should render the waitlist form at all — checked
    on page load rather than only at submit time, so a disabled waitlist
    never flashes a form that would just 404."""
    return WaitlistStatusResponse(enabled=settings.waitlist_enabled)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WaitlistEntryResponse)
async def join_waitlist(
    payload: WaitlistJoinRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WaitlistEntryResponse:
    """Join the waitlist. 404 while the flag is off — the route doesn't
    functionally exist, matching the frontend hiding the form in that state.
    409 on a duplicate email (case-insensitive; addresses are normalized to
    lowercase, matching the auth.py convention)."""
    if not settings.waitlist_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    email = payload.email.lower()
    existing = await db.scalar(select(WaitlistEntry).where(WaitlistEntry.email == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that email is already on the waitlist",
        )

    entry = WaitlistEntry(email=email)
    db.add(entry)
    try:
        # Flush now so a concurrent duplicate join surfaces as an
        # IntegrityError here, not an unhandled error at the caller's commit
        # (same race-safety idiom as the club-join path, MYS-32).
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that email is already on the waitlist",
        ) from None
    await db.commit()
    await db.refresh(entry)
    return WaitlistEntryResponse(id=str(entry.id), email=entry.email, created_at=entry.created_at)
