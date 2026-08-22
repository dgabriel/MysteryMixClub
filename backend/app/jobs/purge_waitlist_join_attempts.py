"""Trim stale rows from ``waitlist_join_attempts`` (MysteryMixClub-dicr).

``POST /waitlist`` records one row per hit so it can rate-limit by counting a
1-hour window per IP. Every hit is recorded regardless of outcome (success,
409 duplicate, or 429 itself is never recorded — see ``_check_join_rate_limit``
in ``waitlist.py``), so nothing about normal usage ever deletes old rows —
this job is the only thing that does, same as ``purge_oauth_callback_attempts``.

Rows older than the retention window are dead weight: the limiter only ever
reads the last hour. A day of retention leaves an enormous margin over that
window while keeping the table small, matching purge_login_attempts's choice.

Invoked by an external scheduler (systemd timer) as a standalone process, the
same shape as ``app.jobs.purge_login_attempts``:

    python -m app.jobs.purge_waitlist_join_attempts

Not yet wired to an actual systemd timer on either Droplet -- that's tracked
generally for all purge/advance jobs under MysteryMixClub-9ej6, not
duplicated here for just this one job.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import CursorResult, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.waitlist_join_attempt import WaitlistJoinAttempt

_RETENTION_HOURS = 24


async def purge_stale_waitlist_join_attempts(
    db: AsyncSession, *, now: datetime | None = None, retention_hours: int = _RETENTION_HOURS
) -> int:
    """Delete waitlist join attempts older than ``retention_hours``, returning
    the count."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=retention_hours)

    result = await db.execute(
        delete(WaitlistJoinAttempt).where(WaitlistJoinAttempt.created_at < cutoff)
    )
    await db.commit()
    # DELETE always yields a CursorResult, but execute() is typed as the
    # narrower Result, which doesn't declare rowcount.
    return cast("CursorResult[Any]", result).rowcount


async def _run() -> None:
    async with async_session_factory() as db:
        count = await purge_stale_waitlist_join_attempts(db)
    print(f"purged {count} stale waitlist join attempt(s)")


if __name__ == "__main__":
    asyncio.run(_run())
