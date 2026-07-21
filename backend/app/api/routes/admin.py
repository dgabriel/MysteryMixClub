import logging
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.wire import WireModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.clubs import (
    _INVITE_TOKEN_BYTES,
    _INVITE_TTL,
    InviteResponse,
    _to_invite_response,
)
from app.auth.deps import get_platform_admin
from app.config import Settings, get_settings
from app.db.session import get_db
from app.jobs.purge_accounts import hard_delete_users
from app.models.invite import Invite
from app.models.user import User
from app.models.waitlist_entry import WaitlistEntry
from app.services.email import EmailSender, get_email_sender
from app.services.notifications import send_waitlist_invite

logger = logging.getLogger("app.api.routes.admin")

router = APIRouter(prefix="/admin", tags=["admin"])

# Cap on the user-search result set — enough to find a target, bounded so a
# broad substring can't return the whole table.
_USER_SEARCH_LIMIT = 50


class AdminUserResponse(WireModel):
    id: str
    email: str
    display_name: str
    created_at: datetime


@router.get("/users", response_model=list[AdminUserResponse])
async def search_users(
    email: str,
    _admin: User = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AdminUserResponse]:
    """Find live accounts whose email contains ``email`` (platform-admin)."""
    users = await db.scalars(
        select(User)
        .where(User.email.ilike(f"%{email}%"), User.deleted_at.is_(None))
        .order_by(User.created_at.asc())
        .limit(_USER_SEARCH_LIMIT)
    )
    return [
        AdminUserResponse(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            created_at=user.created_at,
        )
        for user in users
    ]


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    admin: User = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Hard-delete an account and all its data globally (platform-admin, MYS-128).

    Self-deletion is blocked — admins use /users/me for their own account.
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="use /users/me to delete your own account",
        )

    user = await db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    # Capture the identifiers the cascade needs before deleting the row.
    target_id = user.id
    target_email = user.email
    await hard_delete_users(db, [target_id], [target_email])
    await db.commit()


@router.post("/invites", status_code=201, response_model=InviteResponse)
async def create_platform_invite(
    admin: User = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> InviteResponse:
    """Generate a platform invite (MYS-182): grants signup only, no club
    attachment — the recipient can create their own club (or later, join an
    open one). Same shareable-link shape and 48h expiry as a club invite;
    regenerating from this screen is one click, so that stays low-friction."""
    invite = Invite(
        club_id=None,
        created_by=admin.id,
        token=secrets.token_urlsafe(_INVITE_TOKEN_BYTES),
        expires_at=datetime.now(timezone.utc) + _INVITE_TTL,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return _to_invite_response(invite)


# --------------------------------------------------------------------------- #
# Waitlist (MYS-215, temporary) — the join endpoint is public, in
# app/api/routes/waitlist.py. Everything here is platform-admin only.
# --------------------------------------------------------------------------- #


class WaitlistEntryResponse(WireModel):
    id: str
    email: str
    created_at: datetime
    invited_at: datetime | None
    invited_by: str | None


def _to_waitlist_response(entry: WaitlistEntry) -> WaitlistEntryResponse:
    return WaitlistEntryResponse(
        id=str(entry.id),
        email=entry.email,
        created_at=entry.created_at,
        invited_at=entry.invited_at,
        invited_by=str(entry.invited_by) if entry.invited_by is not None else None,
    )


@router.get("/waitlist", response_model=list[WaitlistEntryResponse])
async def list_waitlist(
    _admin: User = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> list[WaitlistEntryResponse]:
    """Every waitlist entry, oldest first — first come, first invited."""
    entries = await db.scalars(select(WaitlistEntry).order_by(WaitlistEntry.created_at.asc()))
    return [_to_waitlist_response(e) for e in entries]


@router.post("/waitlist/{entry_id}/invite", response_model=WaitlistEntryResponse)
async def invite_from_waitlist(
    entry_id: uuid.UUID,
    admin: User = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    settings: Settings = Depends(get_settings),
) -> WaitlistEntryResponse:
    """Mint a platform invite for a waitlist entry and email it — a club-less,
    48h-expiry invite like POST /admin/invites already creates, but locked to
    this entry's email (MYS-215) so only that address can redeem it.

    Resendable: inviting an already-invited entry is allowed and mints a
    fresh invite (the original link may have expired unused), re-stamping
    invited_at/invited_by to the latest send.

    Sends before persisting anything: the email is the only way the
    recipient learns their invite exists, so a delivery failure must not
    leave the entry marked "invited" with a link nobody received. On
    failure, nothing is added to the session — there's nothing to roll back.
    """
    entry = await db.scalar(select(WaitlistEntry).where(WaitlistEntry.id == entry_id))
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="waitlist entry not found"
        )

    token = secrets.token_urlsafe(_INVITE_TOKEN_BYTES)
    invite_url = f"{settings.app_base_url.rstrip('/')}/invite/{token}"
    try:
        send_waitlist_invite(sender, settings, entry.email, invite_url)
    except Exception:
        logger.exception("failed to send waitlist invite email to %s", entry.email)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="couldn't send the invite email right now. try again.",
        ) from None

    invite = Invite(
        club_id=None,
        created_by=admin.id,
        token=token,
        expires_at=datetime.now(timezone.utc) + _INVITE_TTL,
        # Locks redemption to the waitlisted address (MYS-215) — a link that
        # leaks or gets forwarded can't be used by someone else.
        email=entry.email,
    )
    db.add(invite)
    entry.invited_at = datetime.now(timezone.utc)
    entry.invited_by = admin.id
    await db.commit()
    await db.refresh(entry)

    return _to_waitlist_response(entry)
