import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.invite import Invite
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.note import Note
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote

router = APIRouter(prefix="/leagues", tags=["leagues"])

LeagueName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
LeagueDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class LeagueCreate(BaseModel):
    name: LeagueName
    # Default 6; the backend auto-generates this many pending rounds at creation.
    # Upper-bounded to keep slate sizes sane.
    total_rounds: int = Field(default=6, ge=1, le=50)
    votes_per_player: int = Field(default=3, ge=1)
    # How many songs a player may submit per round (MYS-116). Fixed for the
    # league at setup; 1 (default) = classic one-song behaviour, capped at 5.
    songs_per_submission: int = Field(default=1, ge=1, le=5)
    description: LeagueDescription | None = None
    # Admin-set default participation mode for the league (MYS-112). Seeds every
    # member's vibe_mode at join (including the organizer at creation).
    default_vibe_mode: bool = False
    # Deadline windows (in hours) for the league's rounds (MYS-159). Seed each
    # round's submission/voting deadline when it opens; hour-granular, 4..168 (1
    # week), default 72 (3 days).
    submission_window_hours: int = Field(default=72, ge=4, le=168)
    voting_window_hours: int = Field(default=72, ge=4, le=168)


class LeagueUpdate(BaseModel):
    # All fields optional: only those explicitly provided are applied.
    name: LeagueName | None = None
    description: LeagueDescription | None = None
    # Same upper bound as create: the reconcile grow path bulk-inserts rounds,
    # so cap it here too to keep slate sizes sane.
    total_rounds: int | None = Field(default=None, ge=1, le=50)
    # Changing the league default only affects members who join afterward; it does
    # not re-seed existing members' settings (MYS-112).
    default_vibe_mode: bool | None = None
    # Deadline windows (in hours) for the league's rounds (MYS-159); 4..168. Only
    # affects rounds opened after the change — deadlines already stamped stay put.
    submission_window_hours: int | None = Field(default=None, ge=4, le=168)
    voting_window_hours: int | None = Field(default=None, ge=4, le=168)

    # These all map to NOT NULL columns: allow omission (partial update) but reject
    # an explicitly provided null with a 422. description is nullable, so an
    # explicit null is allowed and clears it.
    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null(cls, data):
        if isinstance(data, dict):
            for field in (
                "name",
                "total_rounds",
                "default_vibe_mode",
                "submission_window_hours",
                "voting_window_hours",
            ):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} may not be null")
        return data


# Number of random bytes for invite tokens, matching the magic-link idiom.
# token_urlsafe(32) yields a 43-character URL-safe string.
_INVITE_TOKEN_BYTES = 32
# Shareable invite links expire 48h after creation (MYS-126); after that the
# organizer must generate a fresh link. Mirrors auth's _TOKEN_TTL idiom.
_INVITE_TTL = timedelta(hours=48)


class InviteResponse(BaseModel):
    id: str
    # Null for a platform (league-less) invite (MYS-182).
    league_id: str | None
    token: str
    created_by: str
    created_at: datetime
    expires_at: datetime | None


def _to_invite_response(invite: Invite) -> InviteResponse:
    return InviteResponse(
        id=str(invite.id),
        league_id=str(invite.league_id) if invite.league_id is not None else None,
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
    songs_per_submission: int
    current_round: int
    state: str
    # Admin-set default participation mode for the league (MYS-112). A member's own
    # setting lives on their membership (GET /leagues/:id/membership), not here.
    default_vibe_mode: bool
    # Deadline windows (in hours) for the league's rounds (MYS-159).
    submission_window_hours: int
    voting_window_hours: int
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
        songs_per_submission=league.songs_per_submission,
        current_round=league.current_round,
        state=league.state,
        default_vibe_mode=league.default_vibe_mode,
        submission_window_hours=league.submission_window_hours,
        voting_window_hours=league.voting_window_hours,
        created_at=league.created_at,
        completed_at=league.completed_at,
    )


class MemberResponse(BaseModel):
    # Privacy-safe member shape: no email is exposed to fellow members.
    user_id: str
    display_name: str
    joined_at: datetime
    is_organizer: bool
    # True if this member is the fixed organizer OR a promoted co-organizer
    # (league_members.role == "admin", MYS-99). Broader than is_organizer, which
    # only ever means "is the original organizer_id".
    is_admin: bool


def _to_member_response(
    member: LeagueMember, user: User, organizer_id: uuid.UUID | None
) -> MemberResponse:
    is_organizer = member.user_id == organizer_id
    return MemberResponse(
        user_id=str(member.user_id),
        display_name=user.display_name,
        joined_at=member.joined_at,
        is_organizer=is_organizer,
        is_admin=is_organizer or member.role == "admin",
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
        songs_per_submission=payload.songs_per_submission,
        default_vibe_mode=payload.default_vibe_mode,
        submission_window_hours=payload.submission_window_hours,
        voting_window_hours=payload.voting_window_hours,
    )
    db.add(league)
    # Flush to populate league.id for the membership and round rows below.
    await db.flush()

    # The organizer is the league's first member; seed their vibe_mode from the
    # league default like any other member (MYS-112).
    member = LeagueMember(
        league_id=league.id,
        user_id=current_user.id,
        vibe_mode=payload.default_vibe_mode,
    )
    db.add(member)

    # Auto-generate the full slate of pending rounds (MYS-62). Each starts with
    # no theme/description; the organizer fills those in while the round is
    # pending. current_round stays 0 until a round is opened.
    for number in range(1, payload.total_rounds + 1):
        db.add(
            Round(
                league_id=league.id,
                round_number=number,
                theme=None,
                description=None,
                state="pending",
                votes_per_player=payload.votes_per_player,
            )
        )

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
    """Load a league or 404, then require the caller to be an organizer or 403.

    "Organizer" here means either the league's fixed ``organizer_id`` or an
    active (``removed_at IS NULL``) league member promoted to co-organizer
    (``league_members.role == "admin"``, MYS-99). Co-organizers get full
    operational parity with the organizer everywhere this helper gates,
    including reuse by :mod:`app.api.routes.rounds`.
    """
    league = await db.scalar(select(League).where(League.id == league_id))
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="league not found")
    if league.organizer_id != current_user.id:
        is_admin_member = await db.scalar(
            select(LeagueMember.id).where(
                LeagueMember.league_id == league_id,
                LeagueMember.user_id == current_user.id,
                LeagueMember.removed_at.is_(None),
                LeagueMember.role == "admin",
            )
        )
        if is_admin_member is None:
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


class LeagueLeaderboardEntry(BaseModel):
    user_id: str
    display_name: str
    vote_count: int
    rank: int


@router.get("/{league_id}/leaderboard", response_model=list[LeagueLeaderboardEntry])
async def get_league_leaderboard(
    league_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LeagueLeaderboardEntry]:
    """All-time vote totals per member, across closed rounds only (MYS-157).

    Every active member appears — those with no closed-round submissions show 0.
    Ordered by votes descending, then display_name ascending for stable tie-breaking.
    """
    await _load_league_as_member(league_id, current_user, db)

    closed_round_ids = select(Round.id).where(
        Round.league_id == league_id,
        Round.state == "closed",
    )

    rows = (
        await db.execute(
            select(
                User.id.label("user_id"),
                User.display_name,
                func.count(Vote.id).label("vote_count"),
            )
            .select_from(LeagueMember)
            .join(User, User.id == LeagueMember.user_id)
            .outerjoin(
                Submission,
                and_(
                    Submission.user_id == LeagueMember.user_id,
                    Submission.round_id.in_(closed_round_ids),
                ),
            )
            .outerjoin(Vote, Vote.submission_id == Submission.id)
            .where(
                LeagueMember.league_id == league_id,
                LeagueMember.removed_at.is_(None),
            )
            .group_by(User.id, User.display_name)
            .order_by(func.count(Vote.id).desc(), User.display_name.asc())
        )
    ).all()

    entries: list[LeagueLeaderboardEntry] = []
    rank = 0
    prev_votes: int | None = None
    for i, row in enumerate(rows):
        if row.vote_count != prev_votes:
            rank = i + 1
            prev_votes = row.vote_count
        entries.append(
            LeagueLeaderboardEntry(
                user_id=str(row.user_id),
                display_name=row.display_name,
                vote_count=row.vote_count,
                rank=rank,
            )
        )
    return entries


class MembershipResponse(BaseModel):
    # The caller's own per-league participation setting (MYS-112). Vibing is
    # private, so this only ever reports the caller's own setting — never anyone
    # else's (the members list deliberately omits it).
    league_id: str
    user_id: str
    vibe_mode: bool


class MembershipUpdate(BaseModel):
    vibe_mode: bool


async def _load_active_membership(
    league_id: uuid.UUID, current_user: User, db: AsyncSession
) -> LeagueMember:
    """Load the caller's active membership for a league, gating on 404/403 first."""
    await _load_league_as_member(league_id, current_user, db)
    membership = await db.scalar(
        select(LeagueMember).where(
            LeagueMember.league_id == league_id,
            LeagueMember.user_id == current_user.id,
            LeagueMember.removed_at.is_(None),
        )
    )
    # _load_league_as_member already proved an active membership exists.
    assert membership is not None
    return membership


@router.get("/{league_id}/membership", response_model=MembershipResponse)
async def get_my_membership(
    league_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MembershipResponse:
    membership = await _load_active_membership(league_id, current_user, db)
    return MembershipResponse(
        league_id=str(league_id),
        user_id=str(current_user.id),
        vibe_mode=membership.vibe_mode,
    )


@router.patch("/{league_id}/membership", response_model=MembershipResponse)
async def set_my_membership(
    league_id: uuid.UUID,
    payload: MembershipUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MembershipResponse:
    membership = await _load_active_membership(league_id, current_user, db)
    membership.vibe_mode = payload.vibe_mode
    await db.commit()
    return MembershipResponse(
        league_id=str(league_id),
        user_id=str(current_user.id),
        vibe_mode=membership.vibe_mode,
    )


@router.patch("/{league_id}", response_model=LeagueResponse)
async def update_league(
    league_id: uuid.UUID,
    payload: LeagueUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeagueResponse:
    league = await _load_league_as_organizer(
        league_id, current_user, db, "only an organizer or co-organizer can update this league"
    )
    if league.state == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="league is complete")

    updates = payload.model_dump(exclude_unset=True)
    new_total = updates.pop("total_rounds", None)

    if new_total is not None and new_total != league.total_rounds:
        await _reconcile_rounds(league, new_total, db)
        league.total_rounds = new_total

    for field, value in updates.items():
        setattr(league, field, value)
    await db.commit()
    await db.refresh(league)
    return _to_response(league)


async def _reconcile_rounds(league: League, new_total: int, db: AsyncSession) -> None:
    """Grow or shrink a league's pending round slate to match ``new_total``.

    INCREASE: append pending rounds numbered (current_max+1 .. new_total).
    DECREASE: delete rounds numbered above new_total — but only if every one of
    them is still ``pending``; a started round (open_submission/open_voting/
    closed) can never be removed (409).
    """
    if new_total < league.current_round:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="total_rounds cannot be below current_round",
        )

    rounds = list(
        await db.scalars(
            select(Round).where(Round.league_id == league.id).order_by(Round.round_number.asc())
        )
    )
    current_max = rounds[-1].round_number if rounds else 0

    if new_total > current_max:
        # Grow: append new pending rounds with no theme/description.
        for number in range(current_max + 1, new_total + 1):
            db.add(
                Round(
                    league_id=league.id,
                    round_number=number,
                    theme=None,
                    description=None,
                    state="pending",
                    votes_per_player=league.votes_per_player,
                )
            )
    elif new_total < current_max:
        # Shrink: the rounds above new_total must all still be pending.
        to_remove = [r for r in rounds if r.round_number > new_total]
        if any(r.state != "pending" for r in to_remove):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="cannot remove rounds that have already started",
            )
        for r in to_remove:
            await db.delete(r)


@router.delete("/{league_id}", status_code=204)
async def delete_league(
    league_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _load_league_as_organizer(
        league_id, current_user, db, "only an organizer or co-organizer can delete this league"
    )
    # The organizer may delete the league in any state (MYS-137) — including an
    # in-progress round. The two-step UI confirm guards the destructive intent;
    # the cascade below removes everything the league owns.

    # Cascade in FK dependency order in one transaction (no ON DELETE CASCADE):
    # votes/notes/submissions (by this league's rounds) -> rounds -> invites ->
    # members -> league.
    round_ids = select(Round.id).where(Round.league_id == league_id)
    await db.execute(delete(Vote).where(Vote.round_id.in_(round_ids)))
    await db.execute(delete(Note).where(Note.round_id.in_(round_ids)))
    await db.execute(delete(Submission).where(Submission.round_id.in_(round_ids)))
    await db.execute(delete(Round).where(Round.league_id == league_id))
    await db.execute(delete(Invite).where(Invite.league_id == league_id))
    await db.execute(delete(LeagueMember).where(LeagueMember.league_id == league_id))
    await db.execute(delete(League).where(League.id == league_id))
    await db.commit()


@router.delete("/{league_id}/members/{user_id}", status_code=204)
async def remove_member(
    league_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if user_id == current_user.id:
        # Self-leave: any active member except the organizer may leave.
        league = await _load_league_as_member(league_id, current_user, db)
        if user_id == league.organizer_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="organizers cannot leave their own league",
            )
    else:
        # Organizer removing another member.
        league = await _load_league_as_organizer(
            league_id, current_user, db, "only an organizer or co-organizer can remove members"
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


class MemberRoleUpdate(BaseModel):
    role: Literal["admin", "member"]


@router.patch("/{league_id}/members/{user_id}/role", response_model=MemberResponse)
async def set_member_role(
    league_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MemberRoleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    """Promote/demote an active member to/from co-organizer (MYS-99).

    Any current admin (the fixed organizer or an existing co-organizer) may
    call this. The organizer's own membership row can't be changed here — its
    admin power comes from ``organizer_id`` itself, not a toggleable role.
    """
    league = await _load_league_as_organizer(
        league_id, current_user, db, "only an organizer or co-organizer can change member roles"
    )
    if user_id == league.organizer_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the organizer already has full admin access and can't be changed here",
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

    # Zero-effective-admins lockout guard (MYS-99 follow-up). If the fixed
    # organizer account has been hard-purged (organizer_id nulled — see
    # jobs/purge_accounts.py), the league's only path to an admin-capable
    # caller is a co-organizer with role == "admin". Demoting the last one
    # would leave the league permanently unadministrable, so block it.
    if payload.role == "member" and membership.role == "admin" and league.organizer_id is None:
        other_admin = await db.scalar(
            select(LeagueMember.id)
            .join(User, User.id == LeagueMember.user_id)
            .where(
                LeagueMember.league_id == league_id,
                LeagueMember.user_id != user_id,
                LeagueMember.removed_at.is_(None),
                LeagueMember.role == "admin",
                User.deleted_at.is_(None),
            )
        )
        if other_admin is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="cannot remove the last admin from a league with no organizer",
            )

    membership.role = payload.role
    await db.commit()

    user = await db.scalar(select(User).where(User.id == user_id))
    assert user is not None
    return _to_member_response(membership, user, league.organizer_id)


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

    # Shareable-link invite with a 48h expiry (MYS-126); after that the organizer
    # must generate a fresh link.
    invite = Invite(
        league_id=league_id,
        created_by=current_user.id,
        token=secrets.token_urlsafe(_INVITE_TOKEN_BYTES),
        expires_at=datetime.now(timezone.utc) + _INVITE_TTL,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return _to_invite_response(invite)


@router.delete("/{league_id}/invites/{invite_id}", status_code=204)
async def revoke_invite(
    league_id: uuid.UUID,
    invite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _load_league_as_organizer(
        league_id, current_user, db, "only an organizer or co-organizer can revoke invites"
    )

    invite = await db.scalar(select(Invite).where(Invite.id == invite_id))
    if invite is None or invite.league_id != league_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")

    # Revoke a shareable link: drop the invite row so the link stops working.
    # Membership is managed separately (remove_member); no email mapping here.
    await db.delete(invite)
    await db.commit()
