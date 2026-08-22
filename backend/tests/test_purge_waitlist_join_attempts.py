"""Tests for MysteryMixClub-dicr: purge_stale_waitlist_join_attempts.

Same shape as test_purge_oauth_callback_attempts.py (that job's shared
"delete rows older than a cutoff" logic already proves the generic
mechanics; not re-litigated here). Just confirms it's wired to the right
model/table.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.jobs.purge_waitlist_join_attempts import purge_stale_waitlist_join_attempts
from app.models.waitlist_join_attempt import WaitlistJoinAttempt

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


async def _count(db_session) -> int:
    return await db_session.scalar(select(func.count()).select_from(WaitlistJoinAttempt))


async def test_purges_attempts_older_than_retention(db_session):
    db_session.add(WaitlistJoinAttempt(ip="1.2.3.4", created_at=NOW - timedelta(hours=25)))
    await db_session.commit()

    purged = await purge_stale_waitlist_join_attempts(db_session, now=NOW)

    assert purged == 1
    assert await _count(db_session) == 0


async def test_keeps_attempts_inside_the_rate_limit_window(db_session):
    # The limiter reads the last hour; retention must never cut into that.
    db_session.add(WaitlistJoinAttempt(ip="1.2.3.4", created_at=NOW - timedelta(minutes=30)))
    await db_session.commit()

    await purge_stale_waitlist_join_attempts(db_session, now=NOW)

    assert await _count(db_session) == 1


async def test_purges_only_the_stale_rows_of_a_mixed_set(db_session):
    for hours in (48, 25, 23, 1):
        db_session.add(WaitlistJoinAttempt(ip="5.6.7.8", created_at=NOW - timedelta(hours=hours)))
    await db_session.commit()

    purged = await purge_stale_waitlist_join_attempts(db_session, now=NOW)

    assert purged == 2
    assert await _count(db_session) == 2
