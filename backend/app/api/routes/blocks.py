"""Block endpoints (MysteryMixClub-4vii.42).

App Store Guideline 1.2 requires a UGC app to let users block abusive users,
not just report their content. The block itself lives here; the *effect* is
read-side and spread across the surfaces that show member-authored text
(notes on every surface, the submitter note on playlist/reveal, reveal voter
attribution) -- see ``app/services/blocks.py`` and ADR 0035.

* ``POST   /api/v1/users/me/blocks``            -- block a member (idempotent)
* ``GET    /api/v1/users/me/blocks``            -- who the caller has blocked
* ``DELETE /api/v1/users/me/blocks/{user_id}``  -- unblock
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.wire import WireModel
from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.block import Block
from app.models.club_member import ClubMember
from app.models.user import User

router = APIRouter(tags=["blocks"])

_NOT_FOUND = "member not found"


class BlockCreate(WireModel):
    user_id: uuid.UUID


class BlockResponse(WireModel):
    user_id: str
    display_name: str
    created_at: datetime


def _to_response(block: Block, display_name: str) -> BlockResponse:
    return BlockResponse(
        user_id=str(block.blocked_id),
        display_name=display_name,
        created_at=block.created_at,
    )


async def _load_blockable_target(user_id: uuid.UUID, current_user: User, db: AsyncSession) -> User:
    """The user the caller wants to block, or a neutral 404.

    One "member not found" covers three cases on purpose -- unknown id,
    deleted account, and a user the caller has never shared a club with -- so
    the endpoint is not a user-existence oracle. The ever-shared-a-club rule
    counts *removed* memberships too: a removed member's notes still show at
    a closed mix's reveal, so they must remain blockable (ADR 0035).
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="you can't block yourself",
        )
    target = await db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)

    mine = aliased(ClubMember)
    theirs = aliased(ClubMember)
    ever_shared_a_club = await db.scalar(
        select(mine.id)
        .join(theirs, mine.club_id == theirs.club_id)
        .where(mine.user_id == current_user.id, theirs.user_id == user_id)
        .limit(1)
    )
    if ever_shared_a_club is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return target


@router.post("/users/me/blocks", status_code=201, response_model=BlockResponse)
async def create_block(
    payload: BlockCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BlockResponse:
    target = await _load_blockable_target(payload.user_id, current_user, db)

    existing = await db.scalar(
        select(Block).where(Block.blocker_id == current_user.id, Block.blocked_id == target.id)
    )
    if existing is not None:
        # Idempotent: re-blocking someone you already blocked is a no-op that
        # returns the standing block, so a retried request or a double-tap
        # can't fail. The 200 (vs 201) marks "nothing new happened".
        response.status_code = status.HTTP_200_OK
        return _to_response(existing, target.display_name)

    block = Block(blocker_id=current_user.id, blocked_id=target.id)
    db.add(block)
    await db.commit()
    await db.refresh(block)
    return _to_response(block, target.display_name)


@router.get("/users/me/blocks", response_model=list[BlockResponse])
async def list_blocks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BlockResponse]:
    rows = await db.execute(
        select(Block, User.display_name)
        .join(User, User.id == Block.blocked_id)
        .where(Block.blocker_id == current_user.id)
        .order_by(Block.created_at.desc())
    )
    return [_to_response(block, display_name) for block, display_name in rows.all()]


@router.delete("/users/me/blocks/{user_id}", status_code=204)
async def delete_block(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    block = await db.scalar(
        select(Block).where(Block.blocker_id == current_user.id, Block.blocked_id == user_id)
    )
    if block is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="you haven't blocked this member",
        )
    await db.delete(block)
    await db.commit()
