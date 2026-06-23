from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, StringConstraints, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.league import League
from app.models.session import Session
from app.models.user import User

router = APIRouter(prefix="/users", tags=["users"])

# Allowed streaming services per the data model (TD 6).
PreferredService = Literal["spotify", "youtube", "deezer"]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class UserProfileResponse(BaseModel):
    id: str
    display_name: str
    email: str
    preferred_service: str | None
    default_vibe_mode: bool
    email_notifications: bool


class UserProfileUpdate(BaseModel):
    # All fields optional: only those explicitly provided are applied. email is
    # intentionally not updatable.
    display_name: DisplayName | None = None
    preferred_service: PreferredService | None = None
    default_vibe_mode: bool | None = None
    email_notifications: bool | None = None

    # display_name, default_vibe_mode and email_notifications map to NOT NULL
    # columns: allow omission (partial update) but reject an explicit null (422).
    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null(cls, data):
        if isinstance(data, dict):
            for field in ("display_name", "default_vibe_mode", "email_notifications"):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} may not be null")
        return data


def _to_profile(user: User) -> UserProfileResponse:
    return UserProfileResponse(
        id=str(user.id),
        display_name=user.display_name,
        email=user.email,
        preferred_service=user.preferred_service,
        default_vibe_mode=user.default_vibe_mode,
        email_notifications=user.email_notifications,
    )


@router.get("/me", response_model=UserProfileResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserProfileResponse:
    return _to_profile(current_user)


@router.patch("/me", response_model=UserProfileResponse)
async def update_me(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfileResponse:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    await db.commit()
    return _to_profile(current_user)


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
