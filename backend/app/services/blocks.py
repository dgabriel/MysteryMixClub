"""Shared read-side helper for member blocks (MysteryMixClub-4vii.42).

A block is one-directional: it filters only the *blocker's* reads. Every
surface that shows member-authored free text (or per-item attribution of it)
subtracts the caller's blocked set before responding, so a blocked member's
text never reaches them (ADR 0035).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.block import Block


async def blocked_user_ids(db: AsyncSession, blocker_id: uuid.UUID) -> set[uuid.UUID]:
    """Return the ids of every user ``blocker_id`` has blocked.

    Empty set for a member who has blocked nobody -- callers skip their
    ``NOT IN`` clause in that case, so the common path costs one indexed
    lookup and changes nothing.
    """
    rows = await db.scalars(select(Block.blocked_id).where(Block.blocker_id == blocker_id))
    return set(rows.all())
