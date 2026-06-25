import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_platform_admin
from app.db.session import get_db
from app.jobs.purge_accounts import hard_delete_users
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])

# Cap on the user-search result set — enough to find a target, bounded so a
# broad substring can't return the whole table.
_USER_SEARCH_LIMIT = 50


class AdminUserResponse(BaseModel):
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
