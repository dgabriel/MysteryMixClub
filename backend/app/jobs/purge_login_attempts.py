"""Trim stale rows from ``login_attempts`` (ADR 0007).

``/auth/login`` records one row per FAILED password attempt so it can rate-limit
by counting a 15-minute window. A successful login clears that email's rows, but
an attempt against an address that never logs in successfully — including an
address with no account at all — has nothing to clear it, so the table would
otherwise grow without bound on attacker-supplied input.

Rows older than the retention window are dead weight: the limiter only ever
reads the last 15 minutes. A day of retention leaves an enormous margin over
that window while keeping the table small.

Invoked by an external scheduler (systemd timer) as a standalone process, the
same shape as ``app.jobs.purge_accounts``:

    python -m app.jobs.purge_login_attempts

The delete filters on ``created_at`` alone, which the composite
``(email, created_at)`` index can't serve, so it scans. That's fine at this
cadence — the whole point of running it is that the table stays small.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import CursorResult, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.login_attempt import LoginAttempt

_RETENTION_HOURS = 24


async def purge_stale_login_attempts(
    db: AsyncSession, *, now: datetime | None = None, retention_hours: int = _RETENTION_HOURS
) -> int:
    """Delete login attempts older than ``retention_hours``, returning the count."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=retention_hours)

    result = await db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < cutoff))
    await db.commit()
    # DELETE always yields a CursorResult, but execute() is typed as the
    # narrower Result, which doesn't declare rowcount.
    return cast("CursorResult[Any]", result).rowcount


async def _run() -> None:
    async with async_session_factory() as db:
        count = await purge_stale_login_attempts(db)
    print(f"purged {count} stale login attempt(s)")


if __name__ == "__main__":
    asyncio.run(_run())
