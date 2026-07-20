"""Hard-purge soft-deleted accounts (right to be forgotten, TD 10).

DELETE /users/me soft-deletes an account: it sets ``users.deleted_at`` and
tombstones the email, but leaves submissions/votes/notes/memberships intact so
the 30-day window keeps mix history readable. This job finishes the job — it
hard-deletes every account whose ``deleted_at`` is older than the retention
window, cascading to all personal data in FK-safe order.

It is invoked by an external scheduler (cron/systemd timer) as a standalone
process:

    python -m app.jobs.purge_accounts

It opens its own AsyncSession, runs in a single transaction, prints the number
of accounts purged, and exits.
"""

import asyncio
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.invite import Invite
from app.models.magic_link_token import MagicLinkToken
from app.models.note import Note
from app.models.session import Session
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote

_RETENTION_DAYS = 30


async def hard_delete_users(
    db: AsyncSession, user_ids: Sequence[uuid.UUID], emails: Sequence[str]
) -> None:
    """Hard-delete the given accounts and all their personal data, FK-safe.

    Shared by the scheduled purge (right to be forgotten, TD 10) and the
    platform-admin eject endpoint (MYS-128). Does NOT commit — the caller owns
    the transaction boundary.
    """
    if not user_ids:
        return

    # FK-safe order: children before parents. Notes/votes reference submissions,
    # so they go first; submissions/memberships/sessions/invites reference users
    # next; then magic-link tokens keyed by the tombstoned email; then the
    # organizer FK on clubs is nulled (purged accounts never organize active
    # clubs); finally the users themselves. invites.created_by is a NOT NULL FK
    # with no ON DELETE, so these must go before the user delete to avoid both an
    # IntegrityError and an orphaned PII record.
    await db.execute(delete(Note).where(Note.author_id.in_(user_ids)))
    await db.execute(delete(Vote).where(Vote.voter_id.in_(user_ids)))
    await db.execute(delete(Submission).where(Submission.user_id.in_(user_ids)))
    await db.execute(delete(ClubMember).where(ClubMember.user_id.in_(user_ids)))
    await db.execute(delete(Invite).where(Invite.created_by.in_(user_ids)))
    await db.execute(delete(Session).where(Session.user_id.in_(user_ids)))
    await db.execute(delete(MagicLinkToken).where(MagicLinkToken.email.in_(emails)))
    await db.execute(update(Club).where(Club.organizer_id.in_(user_ids)).values(organizer_id=None))
    await db.execute(delete(User).where(User.id.in_(user_ids)))


async def purge_deleted_accounts(
    db: AsyncSession, *, now: datetime | None = None, retention_days: int = _RETENTION_DAYS
) -> int:
    """Hard-delete accounts soft-deleted more than ``retention_days`` ago.

    Runs in a single transaction and returns the number of accounts purged.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)

    rows = (
        await db.execute(
            select(User.id, User.email).where(
                User.deleted_at.is_not(None), User.deleted_at <= cutoff
            )
        )
    ).all()
    if not rows:
        return 0

    user_ids = [row.id for row in rows]
    emails = [row.email for row in rows]

    await hard_delete_users(db, user_ids, emails)

    await db.commit()
    return len(user_ids)


async def _run() -> None:
    async with async_session_factory() as db:
        count = await purge_deleted_accounts(db)
    print(f"purged {count} account(s)")


if __name__ == "__main__":
    asyncio.run(_run())
