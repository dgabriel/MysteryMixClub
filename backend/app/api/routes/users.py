from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StringConstraints, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/users", tags=["users"])

# Allowed streaming services per the data model (TD 6).
PreferredService = Literal["spotify", "youtube", "deezer"]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class UserProfileResponse(BaseModel):
    display_name: str
    email: str
    preferred_service: str | None
    default_vibe_mode: bool


class UserProfileUpdate(BaseModel):
    # All fields optional: only those explicitly provided are applied. email is
    # intentionally not updatable.
    display_name: DisplayName | None = None
    preferred_service: PreferredService | None = None
    default_vibe_mode: bool | None = None

    # display_name and default_vibe_mode map to NOT NULL columns: allow omission
    # (partial update) but reject an explicitly provided null with a 422.
    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null(cls, data):
        if isinstance(data, dict):
            for field in ("display_name", "default_vibe_mode"):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} may not be null")
        return data


def _to_profile(user: User) -> UserProfileResponse:
    return UserProfileResponse(
        display_name=user.display_name,
        email=user.email,
        preferred_service=user.preferred_service,
        default_vibe_mode=user.default_vibe_mode,
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
