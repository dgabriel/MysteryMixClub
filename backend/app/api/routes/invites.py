import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.api.wire import WireModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.clubs import ClubResponse, _to_response
from app.auth.deps import get_current_user, get_current_user_optional
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.invite import Invite
from app.models.user import User
from app.services.email import EmailSender, get_email_sender
from app.services.notifications import queue_club_joined

router = APIRouter(prefix="/invites", tags=["invites"])

_EXPIRED_LINK_MESSAGE = "this invite link has expired"


def _is_expired(invite: Invite, now: datetime) -> bool:
    """Shareable links expire 48h after creation (MYS-126). Legacy invites with
    no expires_at never expire."""
    return invite.expires_at is not None and invite.expires_at <= now


async def _is_active_member(db: AsyncSession, league_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    membership = await db.scalar(
        select(ClubMember).where(
            ClubMember.club_id == league_id,
            ClubMember.user_id == user_id,
            ClubMember.removed_at.is_(None),
        )
    )
    return membership is not None


async def _join_via_invite(db: AsyncSession, user_id: uuid.UUID, invite: Invite) -> bool:
    """Join ``user_id`` to the invite's club: insert a new membership, or
    reactivate an existing (possibly removed) one in place. Shared by the invite
    accept route and the auto-join on sign-in (MYS-127). The caller commits.

    Returns True if the user actually joined or rejoined (False = already active, no-op)."""
    membership = await db.scalar(
        select(ClubMember)
        .where(
            ClubMember.club_id == invite.club_id,
            ClubMember.user_id == user_id,
        )
        .with_for_update()
    )
    if membership is not None:
        if membership.removed_at is not None:
            membership.removed_at = None
            membership.joined_at = func.now()
            # A returning member keeps their existing vibe_mode; only fresh joins
            # seed from the club default.
            return True
        return False  # already active — caller should not send a welcome email
    else:
        # Seed the new member's per-club vibe_mode from the club default
        # (MYS-112).
        club = await db.scalar(select(Club).where(Club.id == invite.club_id))
        try:
            db.add(
                ClubMember(
                    club_id=invite.club_id,
                    user_id=user_id,
                    vibe_mode=club.default_vibe_mode if club is not None else False,
                )
            )
            # Flush now so IntegrityError surfaces here rather than at caller's
            # commit — lets us recover cleanly inside this function (MYS-32).
            await db.flush()
        except IntegrityError:
            # A concurrent request beat us to the insert; treat as already joined.
            await db.rollback()
            return False
        return True


class InvitePreviewResponse(WireModel):
    # Null for a platform (club-less) invite (MYS-182) — grants signup only,
    # no club to preview.
    league_id: uuid.UUID | None
    league_name: str | None
    member_count: int | None
    # True when the (optionally authenticated) caller is already an active
    # member of this club. The frontend redirects straight into the club
    # rather than showing the join screen — most useful on an expired link,
    # which would otherwise 410 before a legitimate member ever sees it
    # (MYS-181). Always false for a platform invite — there's no club to be
    # a member of.
    already_member: bool = False


@router.get("/{token}", response_model=InvitePreviewResponse)
async def preview_invite(
    token: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> InvitePreviewResponse:
    invite = await db.scalar(select(Invite).where(Invite.token == token))
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")

    if invite.club_id is None:
        # Platform invite (MYS-182): a signup grant with no club to preview.
        # Single-use (follow-up) — an already-used one reads the same as
        # expired, same copy/CTA, no separate frontend state needed. Exception
        # (MYS-183 fix): the same visitor who just consumed it passes through
        # instead of 410ing — onboarding stashes a pending-invite path that
        # redirects back here once it's done, and that visitor already got
        # what the link was for.
        used_by_someone_else = invite.used_at is not None and (
            current_user is None or invite.used_by_user_id != current_user.id
        )
        if _is_expired(invite, datetime.now(timezone.utc)) or used_by_someone_else:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=_EXPIRED_LINK_MESSAGE)
        return InvitePreviewResponse(
            league_id=None, league_name=None, member_count=None, already_member=False
        )

    already_member = (
        await _is_active_member(db, invite.club_id, current_user.id)
        if current_user is not None
        else False
    )

    # An already-active member passes through regardless of expiry (MYS-181).
    if _is_expired(invite, datetime.now(timezone.utc)) and not already_member:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=_EXPIRED_LINK_MESSAGE)

    club = await db.scalar(select(Club).where(Club.id == invite.club_id))
    if club is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")

    member_count = await db.scalar(
        select(func.count())
        .select_from(ClubMember)
        .where(
            ClubMember.club_id == invite.club_id,
            ClubMember.removed_at.is_(None),
        )
    )
    return InvitePreviewResponse(
        league_id=invite.club_id,
        league_name=club.name,
        member_count=member_count or 0,
        already_member=already_member,
    )


@router.post("/{token}/accept", response_model=ClubResponse)
async def accept_invite(
    token: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_sender: EmailSender = Depends(get_email_sender),
) -> ClubResponse:
    invite = await db.scalar(select(Invite).where(Invite.token == token))
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")

    if invite.club_id is None:
        # Platform invite (MYS-182): grants signup only. "Accept" only makes
        # sense for a club invite — the frontend never calls this route for
        # a club-less token, so a stray/direct call is treated as unknown.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")

    membership = await db.scalar(
        select(ClubMember).where(
            ClubMember.club_id == invite.club_id,
            ClubMember.user_id == current_user.id,
        )
    )
    # Accept is idempotent (MYS-135): an existing active member just gets routed
    # to the club rather than an error. Only a new (or previously removed)
    # membership needs the join + commit. An already-active member also passes
    # through regardless of expiry (MYS-181).
    already_active = membership is not None and membership.removed_at is None

    if _is_expired(invite, datetime.now(timezone.utc)) and not already_active:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=_EXPIRED_LINK_MESSAGE)

    club = await db.scalar(select(Club).where(Club.id == invite.club_id))
    if club is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")

    if not already_active:
        joined = await _join_via_invite(db, current_user.id, invite)
        await db.commit()
        if joined:
            queue_club_joined(
                background_tasks,
                email_sender,
                settings,
                current_user.email,
                current_user.id,
                club.id,
                club.name,
            )

    await db.refresh(club)
    return _to_response(club)
