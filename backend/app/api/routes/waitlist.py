"""Public waitlist (MYS-215, temporary pre-launch access-request flow).

Stands in for "email us for an invite" on the login page while
``settings.waitlist_enabled`` is on. A waitlist row is not an invite and not
a user — it only becomes a real signup when an admin acts on it
(``POST /admin/waitlist/{id}/invite``, in ``admin.py``), which mints the same
club-less platform invite ``POST /admin/invites`` already creates and emails
it. The existing club-invite and platform-invite flows are untouched.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import EmailStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.wire import WireModel
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.waitlist_entry import WaitlistEntry

router = APIRouter(prefix="/waitlist", tags=["waitlist"])

# Per-IP throttle on the public join endpoint — it's unauthenticated and each
# request can target a different email, so the per-email cap /auth/request
# uses (counting rows for that address) doesn't apply here; this stops both
# junk-row spam and using the 409 as an enumeration probe. In-memory only:
# resets on restart/redeploy, and only works because staging/prod both run a
# single process (no --workers flag / instance_count: 1) — fine for a
# temporary pre-launch endpoint, not a pattern to copy for something durable.
_JOIN_RATE_LIMIT_MAX = 5
_JOIN_RATE_LIMIT_WINDOW = timedelta(hours=1)
_join_attempts: dict[str, list[datetime]] = {}


def _client_ip(request: Request) -> str:
    """Best-effort client IP for rate limiting. Nginx (staging) and DO App
    Platform's edge (prod) are the sole ingress in front of the app, and both
    set X-Forwarded-For by *appending* their own view of the connecting IP —
    so the LAST entry is what they actually saw and can't be spoofed by a
    client-supplied earlier entry. Falls back to the raw socket peer for
    local dev, where there's no proxy in front."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _check_join_rate_limit(ip: str, now: datetime) -> None:
    attempts = [t for t in _join_attempts.get(ip, ()) if t > now - _JOIN_RATE_LIMIT_WINDOW]
    if len(attempts) >= _JOIN_RATE_LIMIT_MAX:
        _join_attempts[ip] = attempts
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many requests. try again later.",
        )
    attempts.append(now)
    _join_attempts[ip] = attempts


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
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WaitlistEntryResponse:
    """Join the waitlist. 404 while the flag is off — the route doesn't
    functionally exist, matching the frontend hiding the form in that state.
    409 on a duplicate email (case-insensitive; addresses are normalized to
    lowercase, matching the auth.py convention). Rate-limited per IP (see
    _check_join_rate_limit) — checked after the flag check so a disabled
    waitlist still 404s instead of 429ing."""
    if not settings.waitlist_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    _check_join_rate_limit(_client_ip(request), datetime.now(timezone.utc))

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
