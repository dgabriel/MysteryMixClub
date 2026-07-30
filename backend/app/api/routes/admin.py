import logging
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.wire import WireModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.clubs import (
    _INVITE_TOKEN_BYTES,
    _INVITE_TTL,
    InviteResponse,
    _to_invite_response,
)
from app.auth.deps import get_platform_admin
from app.auth.tokens import generate_token, hash_token
from app.config import Settings, get_settings
from app.db.session import get_db
from app.jobs.purge_accounts import hard_delete_users
from app.models.club import Club
from app.models.invite import Invite
from app.models.magic_link_token import MagicLinkToken
from app.models.mix import Mix
from app.models.note import Note
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote
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

    The email links straight to /auth/verify (a pre-minted magic-link token,
    TTL extended to match the invite's 48h instead of the usual 15m), not the
    /invite/:token preview page. That page's "sign in" CTA sends the
    recipient to /login to retype their email and wait on a *second* email —
    confusing, and not what "you're off the waitlist" should feel like. This
    makes the one link in that email behave exactly like a first-time sign-in
    magic link: click it, land in the app, signed in.

    Resendable: inviting an already-invited entry is allowed and mints a
    fresh invite + magic-link token (the originals may have expired unused),
    re-stamping invited_at/invited_by to the latest send.

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

    now = datetime.now(timezone.utc)
    invite_token = secrets.token_urlsafe(_INVITE_TOKEN_BYTES)
    raw_magic_token = generate_token()
    signin_url = (
        f"{settings.app_base_url.rstrip('/')}/auth/verify"
        f"?token={raw_magic_token}&invite={invite_token}"
    )
    try:
        send_waitlist_invite(sender, settings, entry.email, signin_url)
    except Exception:
        logger.exception("failed to send waitlist invite email to %s", entry.email)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="couldn't send the invite email right now. try again.",
        ) from None

    invite = Invite(
        club_id=None,
        created_by=admin.id,
        token=invite_token,
        expires_at=now + _INVITE_TTL,
        # Locks redemption to the waitlisted address (MYS-215) — a link that
        # leaks or gets forwarded can't be used by someone else.
        email=entry.email,
    )
    db.add(invite)
    db.add(
        MagicLinkToken(
            email=entry.email,
            token_hash=hash_token(raw_magic_token),
            created_at=now,
            # Matches the invite's 48h window (and the email copy) rather than
            # the usual 15m /auth/request TTL — this link needs to survive
            # however long it takes someone to notice a waitlist email.
            expires_at=now + _INVITE_TTL,
            used=False,
        )
    )
    entry.invited_at = now
    entry.invited_by = admin.id
    await db.commit()
    await db.refresh(entry)

    return _to_waitlist_response(entry)


# --------------------------------------------------------------------------- #
# Metrics — aggregate counts only (technical-design §10: no user-level
# tracking). Every value here is a COUNT over an existing table.
# --------------------------------------------------------------------------- #


class AdminMetricsResponse(WireModel):
    total_users: int
    total_clubs: int
    active_clubs: int
    complete_clubs: int
    total_mixes: int
    pending_mixes: int
    open_submission_mixes: int
    open_voting_mixes: int
    closed_mixes: int
    total_submissions: int
    avg_submissions_per_mix: float
    total_votes: int
    total_notes: int
    waitlist_total: int
    waitlist_pending: int
    waitlist_invited: int


@router.get("/metrics", response_model=AdminMetricsResponse)
async def get_metrics(
    _admin: User = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminMetricsResponse:
    """Platform-wide aggregate snapshot (platform-admin)."""
    total_users = (
        await db.scalar(select(func.count()).select_from(User).where(User.deleted_at.is_(None)))
        or 0
    )
    club_counts = {
        state: count
        for state, count in (
            await db.execute(select(Club.state, func.count()).group_by(Club.state))
        ).all()
    }
    mix_counts = {
        state: count
        for state, count in (
            await db.execute(select(Mix.state, func.count()).group_by(Mix.state))
        ).all()
    }
    total_submissions = await db.scalar(select(func.count()).select_from(Submission)) or 0
    # Averaged over mixes that actually received a submission: every club
    # auto-creates all of its mixes up front, so dividing by total mixes would
    # mostly measure how far ahead clubs are scheduled.
    mixes_with_submissions = (
        await db.scalar(select(func.count(func.distinct(Submission.mix_id)))) or 0
    )
    total_votes = await db.scalar(select(func.count()).select_from(Vote)) or 0
    total_notes = await db.scalar(select(func.count()).select_from(Note)) or 0
    waitlist_total = await db.scalar(select(func.count()).select_from(WaitlistEntry)) or 0
    waitlist_invited = (
        await db.scalar(
            select(func.count())
            .select_from(WaitlistEntry)
            .where(WaitlistEntry.invited_at.is_not(None))
        )
        or 0
    )

    return AdminMetricsResponse(
        total_users=total_users,
        total_clubs=sum(club_counts.values()),
        active_clubs=club_counts.get("active", 0),
        complete_clubs=club_counts.get("complete", 0),
        total_mixes=sum(mix_counts.values()),
        pending_mixes=mix_counts.get("pending", 0),
        open_submission_mixes=mix_counts.get("open_submission", 0),
        open_voting_mixes=mix_counts.get("open_voting", 0),
        closed_mixes=mix_counts.get("closed", 0),
        total_submissions=total_submissions,
        avg_submissions_per_mix=(
            total_submissions / mixes_with_submissions if mixes_with_submissions else 0.0
        ),
        total_votes=total_votes,
        total_notes=total_notes,
        waitlist_total=waitlist_total,
        waitlist_pending=waitlist_total - waitlist_invited,
        waitlist_invited=waitlist_invited,
    )
