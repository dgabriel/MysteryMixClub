from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.leagues import LeagueResponse, _to_response
from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.invite import Invite
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.user import User

router = APIRouter(prefix="/invites", tags=["invites"])


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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeagueResponse:
    invite = await db.scalar(select(Invite).where(Invite.token == token))
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")

    league = await db.scalar(select(League).where(League.id == invite.league_id))
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")

    membership = await db.scalar(
        select(LeagueMember).where(
            LeagueMember.league_id == invite.league_id,
            LeagueMember.user_id == current_user.id,
        )
    )
    if membership is not None:
        if membership.removed_at is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already a member")
        # Reactivate the existing row in place rather than inserting a second one.
        membership.removed_at = None
        membership.joined_at = func.now()
    else:
        db.add(LeagueMember(league_id=invite.league_id, user_id=current_user.id))

    await db.commit()
    await db.refresh(league)
    return _to_response(league)
