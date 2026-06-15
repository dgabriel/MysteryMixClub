import secrets
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.invite import Invite
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.user import User

router = APIRouter(prefix="/leagues", tags=["leagues"])

LeagueName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
LeagueDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class LeagueCreate(BaseModel):
    name: LeagueName
    total_rounds: int = Field(ge=1)
    votes_per_player: int = Field(default=3, ge=1)
    description: LeagueDescription | None = None


class LeagueUpdate(BaseModel):
    # All fields optional: only those explicitly provided are applied.
    name: LeagueName | None = None
    description: LeagueDescription | None = None
    total_rounds: int | None = Field(default=None, ge=1)

    # name and total_rounds map to NOT NULL columns: allow omission (partial
    # update) but reject an explicitly provided null with a 422. description is
    # nullable, so an explicit null is allowed and clears it.
    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null(cls, data):
        if isinstance(data, dict):
            for field in ("name", "total_rounds"):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} may not be null")
        return data


# Number of random bytes for invite tokens, matching the magic-link idiom.
# token_urlsafe(32) yields a 43-character URL-safe string.
_INVITE_TOKEN_BYTES = 32


class InviteResponse(BaseModel):
    id: str
    league_id: str
    token: str
    created_by: str
    created_at: datetime
    expires_at: datetime | None


def _to_invite_response(invite: Invite) -> InviteResponse:
    return InviteResponse(
        id=str(invite.id),
        league_id=str(invite.league_id),
        token=invite.token,
        created_by=str(invite.created_by),
        created_at=invite.created_at,
        expires_at=invite.expires_at,
    )


class LeagueResponse(BaseModel):
    id: str
    name: str
    description: str | None
    # Null once the organizing account has been hard-purged (MYS-50).
    organizer_id: str | None
    total_rounds: int
    votes_per_player: int
    current_round: int
    state: str
    created_at: datetime
    completed_at: datetime | None


def _to_response(league: League) -> LeagueResponse:
    return LeagueResponse(
        id=str(league.id),
        name=league.name,
        description=league.description,
        organizer_id=str(league.organizer_id) if league.organizer_id is not None else None,
        total_rounds=league.total_rounds,
        votes_per_player=league.votes_per_player,
        current_round=league.current_round,
        state=league.state,
        created_at=league.created_at,
        completed_at=league.completed_at,
    )


class MemberResponse(BaseModel):
    # Privacy-safe member shape: no email is exposed to fellow members.
    user_id: str
    display_name: str
    joined_at: datetime
    is_organizer: bool


def _to_member_response(
    member: LeagueMember, user: User, organizer_id: uuid.UUID | None
) -> MemberResponse:
    return MemberResponse(
        user_id=str(member.user_id),
        display_name=user.display_name,
        joined_at=member.joined_at,
        is_organizer=member.user_id == organizer_id,
    )


@router.post("", status_code=201, response_model=LeagueResponse)
async def create_league(
    payload: LeagueCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeagueResponse:
    league = League(
        name=payload.name,
        description=payload.description,
        organizer_id=current_user.id,
        total_rounds=payload.total_rounds,
        votes_per_player=payload.votes_per_player,
    )
    db.add(league)
    # Flush to populate league.id for the membership row below.
    await db.flush()

    # The organizer is the league's first member.
    member = LeagueMember(league_id=league.id, user_id=current_user.id)
    db.add(member)

    await db.commit()
    await db.refresh(league)
    return _to_response(league)


@router.get("", response_model=list[LeagueResponse])
async def list_leagues(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LeagueResponse]:
    # Every league the caller is an active member of. The organizer holds such
    # a row from league creation, so organized leagues are included naturally.
    leagues = await db.scalars(
        select(League)
        .join(LeagueMember, LeagueMember.league_id == League.id)
        .where(
            LeagueMember.user_id == current_user.id,
            LeagueMember.removed_at.is_(None),
        )
        .order_by(League.created_at.desc())
    )
    return [_to_response(league) for league in leagues]


async def _load_league_as_organizer(
    league_id: uuid.UUID, current_user: User, db: AsyncSession, forbidden_detail: str
) -> League:
    """Load a league or 404, then require the caller to be its organizer or 403."""
    league = await db.scalar(select(League).where(League.id == league_id))
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="league not found")
    if league.organizer_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=forbidden_detail)
    return league


async def _load_league_as_member(
    league_id: uuid.UUID, current_user: User, db: AsyncSession
) -> League:
    """Load a league or 404, then require the caller to be an active member or 403."""
    league = await db.scalar(select(League).where(League.id == league_id))
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="league not found")
    membership = await db.scalar(
        select(LeagueMember).where(
            LeagueMember.league_id == league_id,
            LeagueMember.user_id == current_user.id,
            LeagueMember.removed_at.is_(None),
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you are not a member of this league",
        )
    return league


@router.get("/{league_id}", response_model=LeagueResponse)
async def get_league(
    league_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeagueResponse:
    league = await _load_league_as_member(league_id, current_user, db)
    return _to_response(league)


@router.get("/{league_id}/members", response_model=list[MemberResponse])
async def list_league_members(
    league_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MemberResponse]:
    league = await _load_league_as_member(league_id, current_user, db)
    # Active members joined to their users in one query to avoid an N+1.
    rows = await db.execute(
        select(LeagueMember, User)
        .join(User, User.id == LeagueMember.user_id)
        .where(
            LeagueMember.league_id == league_id,
            LeagueMember.removed_at.is_(None),
        )
        .order_by(LeagueMember.joined_at.asc())
    )
    return [_to_member_response(member, user, league.organizer_id) for member, user in rows.all()]


@router.patch("/{league_id}", response_model=LeagueResponse)
async def update_league(
    league_id: uuid.UUID,
    payload: LeagueUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeagueResponse:
    league = await _load_league_as_organizer(
        league_id, current_user, db, "only the organizer can update this league"
    )
    if league.state == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="league is complete")

    updates = payload.model_dump(exclude_unset=True)
    if "total_rounds" in updates and updates["total_rounds"] < league.current_round:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="total_rounds cannot be below current_round",
        )

    for field, value in updates.items():
        setattr(league, field, value)
    await db.commit()
    await db.refresh(league)
    return _to_response(league)


@router.delete("/{league_id}/members/{user_id}", status_code=204)
async def remove_member(
    league_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    league = await _load_league_as_organizer(
        league_id, current_user, db, "only the organizer can remove members"
    )
    if user_id == league.organizer_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="cannot remove the organizer"
        )

    membership = await db.scalar(
        select(LeagueMember).where(
            LeagueMember.league_id == league_id,
            LeagueMember.user_id == user_id,
            LeagueMember.removed_at.is_(None),
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    membership.removed_at = func.now()
    await db.commit()


@router.post("/{league_id}/invites", status_code=201, response_model=InviteResponse)
async def create_invite(
    league_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InviteResponse:
    league = await db.scalar(select(League).where(League.id == league_id))
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="league not found")

    # Only an active member (removed_at IS NULL) may generate invites. The
    # organizer has such a row from league creation, so the organizer passes.
    membership = await db.scalar(
        select(LeagueMember).where(
            LeagueMember.league_id == league_id,
            LeagueMember.user_id == current_user.id,
            LeagueMember.removed_at.is_(None),
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a member")

    invite = Invite(
        league_id=league_id,
        created_by=current_user.id,
        token=secrets.token_urlsafe(_INVITE_TOKEN_BYTES),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return _to_invite_response(invite)
