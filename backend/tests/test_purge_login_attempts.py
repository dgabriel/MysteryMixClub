"""Tests for MysteryMixClub-ali8.1 (ADR 0007): purge_stale_login_attempts.

/auth/login clears an email's rows on a successful sign-in, but attempts against
an address that never signs in successfully — including one with no account at
all — have nothing to clear them. This scheduled job is what keeps the table
bounded against attacker-supplied input.

Tests call the job directly with an explicit ``now`` so the retention window is
deterministic.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.jobs.purge_login_attempts import purge_stale_login_attempts
from app.models.login_attempt import LoginAttempt

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


async def _count(db_session) -> int:
    return await db_session.scalar(select(func.count()).select_from(LoginAttempt))


async def test_purges_attempts_older_than_retention(db_session):
    db_session.add(LoginAttempt(email="old@example.com", created_at=NOW - timedelta(hours=25)))
    await db_session.commit()

    purged = await purge_stale_login_attempts(db_session, now=NOW)

    assert purged == 1
    assert await _count(db_session) == 0


async def test_keeps_attempts_inside_retention(db_session):
    db_session.add(LoginAttempt(email="recent@example.com", created_at=NOW - timedelta(hours=23)))
    await db_session.commit()

    purged = await purge_stale_login_attempts(db_session, now=NOW)

    assert purged == 0
    assert await _count(db_session) == 1


async def test_keeps_an_attempt_inside_the_rate_limit_window(db_session):
    # The limiter only ever reads the last 15 minutes; retention must never cut
    # into that.
    db_session.add(LoginAttempt(email="live@example.com", created_at=NOW - timedelta(minutes=5)))
    await db_session.commit()

    await purge_stale_login_attempts(db_session, now=NOW)

    assert await _count(db_session) == 1


async def test_purges_only_the_stale_rows_of_a_mixed_set(db_session):
    for hours in (48, 25, 23, 1):
        db_session.add(
            LoginAttempt(email="mixed@example.com", created_at=NOW - timedelta(hours=hours))
        )
    await db_session.commit()

    purged = await purge_stale_login_attempts(db_session, now=NOW)

    assert purged == 2
    assert await _count(db_session) == 2


async def test_is_a_noop_on_an_empty_table(db_session):
    purged = await purge_stale_login_attempts(db_session, now=NOW)

    assert purged == 0


async def test_retention_window_is_configurable(db_session):
    db_session.add(LoginAttempt(email="old@example.com", created_at=NOW - timedelta(hours=2)))
    await db_session.commit()

    purged = await purge_stale_login_attempts(db_session, now=NOW, retention_hours=1)

    assert purged == 1
    assert await _count(db_session) == 0
