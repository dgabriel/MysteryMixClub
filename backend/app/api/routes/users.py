from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, StringConstraints, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.note import Note
from app.models.session import Session
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote

router = APIRouter(prefix="/users", tags=["users"])

# Allowed streaming services per the data model (TD 6).
PreferredService = Literal["spotify", "youtube", "deezer"]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class UserProfileResponse(BaseModel):
    id: str
    display_name: str
    email: str
    preferred_service: str | None
    email_notifications: bool
    # Whether this account may use the platform-admin tools (MYS-128). Derived
    # from SEED_ADMIN_EMAILS so the UI can gate the /admin nav entry.
    is_platform_admin: bool
    # Whether the user has accepted the current Terms of Service / Privacy
    # Policy (MYS-183). Drives the frontend's consent gate.
    tos_accepted: bool


class UserProfileUpdate(BaseModel):
    # All fields optional: only those explicitly provided are applied. email is
    # intentionally not updatable.
    display_name: DisplayName | None = None
    preferred_service: PreferredService | None = None
    email_notifications: bool | None = None
    # Accepting the Terms of Service / Privacy Policy (MYS-183). Only `true` is
    # a meaningful value — there's no client-initiated "unaccept" — so this is
    # the sole literal accepted; the server stamps its own timestamp below,
    # never trusting one from the client.
    accept_terms: Literal[True] | None = None

    # display_name and email_notifications map to NOT NULL columns: allow omission
    # (partial update) but reject an explicit null (422).
    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null(cls, data):
        if isinstance(data, dict):
            for field in ("display_name", "email_notifications"):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} may not be null")
        return data


class ExportSubmission(BaseModel):
    id: str
    round_id: str
    isrc: str
    title: str
    artist: str
    album: str | None
    note: str | None
    participation_mode: str
    created_at: datetime


class ExportVote(BaseModel):
    id: str
    round_id: str
    submission_id: str
    created_at: datetime


class ExportNote(BaseModel):
    id: str
    round_id: str
    submission_id: str
    body: str
    created_at: datetime


class ExportLeagueMembership(BaseModel):
    league_id: str
    league_name: str
    role: str
    joined_at: datetime


class UserDataExportResponse(BaseModel):
    exported_at: datetime
    profile: UserProfileResponse
    submissions: list[ExportSubmission]
    votes: list[ExportVote]
    notes: list[ExportNote]
    league_memberships: list[ExportLeagueMembership]


def _to_profile(user: User, settings: Settings) -> UserProfileResponse:
    return UserProfileResponse(
        id=str(user.id),
        display_name=user.display_name,
        email=user.email,
        preferred_service=user.preferred_service,
        email_notifications=user.email_notifications,
        is_platform_admin=user.email.lower() in settings.seed_admin_email_set,
        tos_accepted=user.tos_accepted_at is not None,
    )


@router.get("/me", response_model=UserProfileResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> UserProfileResponse:
    return _to_profile(current_user, settings)


@router.get("/me/export", response_model=UserDataExportResponse)
async def export_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserDataExportResponse:
    """Right of access / data portability (GDPR Art. 15/20, MYS-185).

    Returns a JSON dump of everything tied to the caller's own account: profile,
    submissions, votes, notes, and league memberships. Read-only — mirrors the
    same tables the hard-purge cascade touches (app.jobs.purge_accounts) but
    selects rather than deletes.
    """
    submissions = await db.scalars(select(Submission).where(Submission.user_id == current_user.id))
    votes = await db.scalars(select(Vote).where(Vote.voter_id == current_user.id))
    notes = await db.scalars(select(Note).where(Note.author_id == current_user.id))
    memberships = await db.execute(
        select(LeagueMember, League.name)
        .join(League, League.id == LeagueMember.league_id)
        .where(LeagueMember.user_id == current_user.id)
    )

    return UserDataExportResponse(
        exported_at=datetime.now(timezone.utc),
        profile=_to_profile(current_user, settings),
        submissions=[
            ExportSubmission(
                id=str(s.id),
                round_id=str(s.round_id),
                isrc=s.isrc,
                title=s.title,
                artist=s.artist,
                album=s.album,
                note=s.note,
                participation_mode=s.participation_mode,
                created_at=s.created_at,
            )
            for s in submissions
        ],
        votes=[
            ExportVote(
                id=str(v.id),
                round_id=str(v.round_id),
                submission_id=str(v.submission_id),
                created_at=v.created_at,
            )
            for v in votes
        ],
        notes=[
            ExportNote(
                id=str(n.id),
                round_id=str(n.round_id),
                submission_id=str(n.submission_id),
                body=n.body,
                created_at=n.created_at,
            )
            for n in notes
        ],
        league_memberships=[
            ExportLeagueMembership(
                league_id=str(member.league_id),
                league_name=league_name,
                role=member.role,
                joined_at=member.joined_at,
            )
            for member, league_name in memberships
        ],
    )


@router.patch("/me", response_model=UserProfileResponse)
async def update_me(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserProfileResponse:
    fields = payload.model_dump(exclude_unset=True, exclude={"accept_terms"})
    for field, value in fields.items():
        setattr(current_user, field, value)
    if payload.accept_terms:
        current_user.tos_accepted_at = datetime.now(timezone.utc)
    await db.commit()
    return _to_profile(current_user, settings)


# Calm, actionable detail when the caller still organizes a live league.
_ACTIVE_LEAGUE_BLOCK = "finish or hand off the leagues you organize before deleting your account"


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete the caller's account (right to be forgotten, TD 10).

    Blocks while the caller organizes an active league. Otherwise it tombstones
    the email (freeing it for re-signup and dropping the PII), invalidates every
    session, and marks the account deleted. Submissions/votes/notes/memberships
    are left intact for round integrity and are removed by the scheduled hard
    purge within 30 days (app.jobs.purge_accounts). The existing deleted_at
    filters in auth already lock the account out of sign-in.
    """
    organizes_active = await db.scalar(
        select(func.count())
        .select_from(League)
        .where(League.organizer_id == current_user.id, League.state == "active")
    )
    if organizes_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_ACTIVE_LEAGUE_BLOCK,
        )

    now = datetime.now(timezone.utc)
    current_user.deleted_at = now
    current_user.email = f"deleted+{current_user.id}@deleted.invalid"

    # Kill every still-active session so refresh tokens die with the account.
    await db.execute(
        update(Session)
        .where(Session.user_id == current_user.id, Session.invalidated_at.is_(None))
        .values(invalidated_at=now)
    )

    await db.commit()
