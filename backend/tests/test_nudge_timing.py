"""The push nudges' time arithmetic (MysteryMixClub-bfqo), on plain datetimes."""

from datetime import datetime, timedelta, timezone

from app.services import nudge_timing as nt

UTC = timezone.utc


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


# --- halfway ---------------------------------------------------------------


def test_halfway_is_the_midpoint():
    assert nt.halfway_at(_utc(2026, 3, 9, 0), _utc(2026, 3, 11, 0)) == _utc(2026, 3, 10, 0)


def test_halfway_needs_a_long_enough_phase():
    opened = _utc(2026, 3, 9, 0)
    assert nt.halfway_at(opened, opened + timedelta(hours=5, minutes=59)) is None
    assert nt.halfway_at(opened, opened + timedelta(hours=6)) == opened + timedelta(hours=3)


# --- due morning -----------------------------------------------------------


def test_due_morning_is_8am_club_time_on_the_deadline_day():
    # 6pm New York (EDT, UTC-4) on 10 March -> 8am that day is 12:00 UTC.
    deadline = _utc(2026, 3, 10, 22)
    assert nt.due_morning_at(_utc(2026, 3, 8, 22), deadline, "America/New_York") == _utc(
        2026, 3, 10, 12
    )


def test_due_morning_uses_the_club_calendar_day_not_the_utc_one():
    # 03:00 UTC on the 11th is 23:00 on the 10th in New York: due day is the 10th.
    deadline = _utc(2026, 3, 11, 3)
    assert nt.due_morning_at(_utc(2026, 3, 8, 3), deadline, "America/New_York") == _utc(
        2026, 3, 10, 12
    )
    # ...but in UTC the same instant is 03:00 on the 11th, before that day's 8am.
    assert nt.due_morning_at(_utc(2026, 3, 8, 3), deadline, "UTC") is None


def test_due_morning_follows_daylight_saving():
    # New York springs forward on 8 March 2026: 8am is 13:00 UTC before, 12:00 after.
    assert nt.due_morning_at(_utc(2026, 3, 5), _utc(2026, 3, 7, 22), "America/New_York") == _utc(
        2026, 3, 7, 13
    )
    assert nt.due_morning_at(_utc(2026, 3, 5), _utc(2026, 3, 9, 22), "America/New_York") == _utc(
        2026, 3, 9, 12
    )


def test_due_morning_skipped_when_the_deadline_is_too_close_to_8am():
    opened = _utc(2026, 3, 8)
    # Deadline 08:59 -> only 59 minutes of lead.
    assert nt.due_morning_at(opened, _utc(2026, 3, 10, 8, 59), "UTC") is None
    assert nt.due_morning_at(opened, _utc(2026, 3, 10, 9, 0), "UTC") == _utc(2026, 3, 10, 8)
    # Deadline before 8am that day: 8am is after it.
    assert nt.due_morning_at(opened, _utc(2026, 3, 10, 6), "UTC") is None


def test_due_morning_skipped_when_the_phase_opened_after_8am_that_day():
    deadline = _utc(2026, 3, 10, 22)
    assert nt.due_morning_at(_utc(2026, 3, 10, 8, 30), deadline, "UTC") is None
    assert nt.due_morning_at(_utc(2026, 3, 10, 8, 0), deadline, "UTC") is None
    assert nt.due_morning_at(_utc(2026, 3, 10, 7, 59), deadline, "UTC") == _utc(2026, 3, 10, 8)


# --- coincidence and grace -------------------------------------------------


def test_scheduled_reminder_times_follow_the_club_window_gate():
    d = _utc(2026, 3, 10, 22)
    opened = d - timedelta(days=3)
    assert nt.scheduled_reminder_times(opened, d, 12) == []
    assert nt.scheduled_reminder_times(opened, d, 13) == [d - timedelta(hours=12)]
    assert nt.scheduled_reminder_times(opened, d, 24) == [d - timedelta(hours=12)]
    assert nt.scheduled_reminder_times(opened, d, 25) == [
        d - timedelta(hours=12),
        d - timedelta(hours=24),
    ]


def test_scheduled_reminders_land_at_the_opening_pass_for_a_short_phase():
    d = _utc(2026, 3, 10, 22)
    # Phase really runs 9h though the club is configured for 72h: the 12h warning
    # fires as soon as it opens; the ~24h push has no band to fire in at all.
    opened = d - timedelta(hours=9)
    assert nt.scheduled_reminder_times(opened, d, 72) == [opened]
    # A 23h phase reaches the 23h edge of the ~24h band right at opening.
    opened = d - timedelta(hours=23)
    assert nt.scheduled_reminder_times(opened, d, 72) == [d - timedelta(hours=12), opened]


def test_due_morning_ignores_an_unknown_timezone():
    assert nt.due_morning_at(_utc(2026, 3, 8), _utc(2026, 3, 10, 22), "Not/AZone") is None


def test_near_any_is_strictly_under_an_hour():
    m = _utc(2026, 3, 10, 12)
    assert nt.near_any(m, [m + timedelta(minutes=59)])
    assert nt.near_any(m, [m - timedelta(minutes=59)])
    assert not nt.near_any(m, [m + timedelta(hours=1)])
    assert not nt.near_any(m, [])


def test_is_due_window_is_moment_up_to_grace():
    m = _utc(2026, 3, 10, 12)
    assert not nt.is_due(m, m - timedelta(seconds=1))
    assert nt.is_due(m, m)
    assert nt.is_due(m, m + timedelta(minutes=59))
    assert not nt.is_due(m, m + timedelta(hours=1))
