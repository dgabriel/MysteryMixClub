import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.leagues import LeagueResponse, _to_response
from app.auth.deps import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.invite import Invite
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.user import User
from app.services.email import EmailSender, get_email_sender
from app.services.notifications import queue_league_joined

router = APIRouter(prefix="/invites", tags=["invites"])

_EXPIRED_LINK_MESSAGE = "this invite link has expired"


def _is_expired(invite: Invite, now: datetime) -> bool:
    """Shareable links expire 48h after creation (MYS-126). Legacy invites with
    no expires_at never expire."""
    return invite.expires_at is not None and invite.expires_at <= now


async def _join_via_invite(db: AsyncSession, user_id: uuid.UUID, invite: Invite) -> bool:
    """Join ``user_id`` to the invite's league: insert a new membership, or
    reactivate an existing (possibly removed) one in place. Shared by the invite
    accept route and the auto-join on sign-in (MYS-127). The caller commits.

    Returns True if the user actually joined or rejoined (False = already active, no-op)."""
    membership = await db.scalar(
        select(LeagueMember).where(
            LeagueMember.league_id == invite.league_id,
            LeagueMember.user_id == user_id,
        )
    )
    if membership is not None:
        if membership.removed_at is not None:
            membership.removed_at = None
            membership.joined_at = func.now()
            # A returning member keeps their existing vibe_mode; only fresh joins
            # seed from the league default.
            return True
        return False  # already active — caller should not send a welcome email
    else:
        # Seed the new member's per-league vibe_mode from the league default
        # (MYS-112).
        league = await db.scalar(select(League).where(League.id == invite.league_id))
        db.add(
            LeagueMember(
                league_id=invite.league_id,
                user_id=user_id,
                vibe_mode=league.default_vibe_mode if league is not None else False,
            )
        )
        return True


class InvitePreviewResponse(BaseModel):
    league_name: str
    member_count: int


@router.get("/{token}", response_model=InvitePreviewResponse)
async def preview_invite(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> InvitePreviewResponse:
    invite = await db.scalar(select(Invite).where(Invite.token == token))
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")

    if _is_expired(invite, datetime.now(timezone.utc)):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=_EXPIRED_LINK_MESSAGE)

    league = await db.scalar(select(League).where(League.id == invite.league_id))
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")

    member_count = await db.scalar(
        select(func.count())
        .select_from(LeagueMember)
        .where(
            LeagueMember.league_id == invite.league_id,
            LeagueMember.removed_at.is_(None),
        )
    )
    return InvitePreviewResponse(league_name=league.name, member_count=member_count or 0)


@router.post("/{token}/accept", response_model=LeagueResponse)
async def accept_invite(
    token: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_sender: EmailSender = Depends(get_email_sender),
) -> LeagueResponse:
    invite = await db.scalar(select(Invite).where(Invite.token == token))
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")

    if _is_expired(invite, datetime.now(timezone.utc)):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=_EXPIRED_LINK_MESSAGE)

    league = await db.scalar(select(League).where(League.id == invite.league_id))
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")

    membership = await db.scalar(
        select(LeagueMember).where(
            LeagueMember.league_id == invite.league_id,
            LeagueMember.user_id == current_user.id,
        )
    )
    # Accept is idempotent (MYS-135): an existing active member just gets routed
    # to the league rather than an error. Only a new (or previously removed)
    # membership needs the join + commit.
    already_active = membership is not None and membership.removed_at is None
    if not already_active:
        await _join_via_invite(db, current_user.id, invite)
        await db.commit()
        queue_league_joined(
            background_tasks,
            email_sender,
            settings,
            current_user.email,
            current_user.id,
            league.id,
            league.name,
        )

    await db.refresh(league)
    return _to_response(league)
