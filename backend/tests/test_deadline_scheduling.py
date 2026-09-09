"""Fast, DB-free unit tests for ADR 0021's deadline-computation helper
(MysteryMixClub-z845): ``compute_phase_deadline`` / ``_next_weekly_occurrence``.

Expected values here were independently computed and verified (not just
reproduced from the implementation) — see the ADR for the reasoning behind
the 24h minimum-lead guard and the DST-fold default.
"""

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest

from app.models.club import Club
from app.services.deadline_scheduling import _next_weekly_occurrence, compute_phase_deadline


def _club(**overrides) -> Club:
    defaults = dict(
        id=uuid.uuid4(),
        name="Test Club",
        total_mixes=6,
        submission_window_hours=72,
        voting_window_hours=72,
        deadline_mode="duration",
        timezone="UTC",
        submission_weekday=None,
        submission_time=None,
        voting_weekday=None,
        voting_time=None,
    )
    defaults.update(overrides)
    return Club(**defaults)


# ========================================================================== #
# compute_phase_deadline — mode dispatch
# ========================================================================== #


def test_duration_mode_unchanged():
    club = _club(deadline_mode="duration", submission_window_hours=6, voting_window_hours=100)
    now = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    assert compute_phase_deadline(club, "submission", now) == now + timedelta(hours=6)
    assert compute_phase_deadline(club, "voting", now) == now + timedelta(hours=100)


def test_weekly_anchor_mode_dispatches_to_configured_phase():
    club = _club(
        deadline_mode="weekly_anchor",
        timezone="UTC",
        submission_weekday=3,  # thursday
        submission_time=time(9, 0),
        voting_weekday=5,  # saturday
        voting_time=time(12, 0),
    )
    now = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)  # tuesday
    assert compute_phase_deadline(club, "submission", now) == datetime(
        2026, 9, 10, 9, 0, tzinfo=timezone.utc
    )
    assert compute_phase_deadline(club, "voting", now) == datetime(
        2026, 9, 12, 12, 0, tzinfo=timezone.utc
    )


def test_weekly_anchor_mode_missing_schedule_raises():
    club = _club(deadline_mode="weekly_anchor", timezone="UTC")  # no weekday/time set
    with pytest.raises(ValueError):
        compute_phase_deadline(club, "submission", datetime.now(timezone.utc))


# ========================================================================== #
# _next_weekly_occurrence — the anchor math itself
# ========================================================================== #


def test_min_lead_rolls_to_next_week_when_today_is_too_soon():
    # Tuesday 10:00 UTC, anchor is Tuesday 12:00 — only 2h away, under the 24h
    # minimum lead, so it rolls to the following Tuesday.
    now = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    assert _next_weekly_occurrence(now, "UTC", 1, time(12, 0)) == datetime(
        2026, 9, 15, 12, 0, tzinfo=timezone.utc
    )


def test_normal_case_lands_on_the_soonest_matching_weekday():
    now = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)  # tuesday
    assert _next_weekly_occurrence(now, "UTC", 3, time(9, 0)) == datetime(
        2026, 9, 10, 9, 0, tzinfo=timezone.utc
    )


def test_same_day_already_passed_rolls_to_next_week():
    now = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)  # tuesday 3pm
    assert _next_weekly_occurrence(now, "UTC", 1, time(12, 0)) == datetime(
        2026, 9, 15, 12, 0, tzinfo=timezone.utc
    )


def test_exactly_24h_lead_is_not_rolled():
    # Boundary is inclusive: exactly 24h out stays put, not >=24h1s.
    now = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    assert _next_weekly_occurrence(now, "UTC", 2, time(10, 0)) == datetime(
        2026, 9, 9, 10, 0, tzinfo=timezone.utc
    )


def test_just_under_24h_lead_is_rolled():
    now = datetime(2026, 9, 8, 10, 1, tzinfo=timezone.utc)
    assert _next_weekly_occurrence(now, "UTC", 2, time(10, 0)) == datetime(
        2026, 9, 16, 10, 0, tzinfo=timezone.utc
    )


def test_non_utc_timezone_no_dst_crossing():
    # now is 2027-03-10 09:00 EST; anchor is Friday the same week, still EST.
    now = datetime(2027, 3, 10, 14, 0, tzinfo=timezone.utc)
    assert _next_weekly_occurrence(now, "America/New_York", 4, time(9, 0)) == datetime(
        2027, 3, 12, 14, 0, tzinfo=timezone.utc
    )


def test_dst_spring_forward_boundary_uses_the_candidate_dates_own_offset():
    # now is 2027-03-10 09:00 EST (pre-transition); the anchor lands on
    # 2027-03-15, AFTER the March 14 spring-forward, so the correct answer
    # uses EDT (-4h), not EST (-5h) carried over from `now`. A naive
    # implementation that reused now's offset would be off by an hour.
    now = datetime(2027, 3, 10, 14, 0, tzinfo=timezone.utc)
    assert _next_weekly_occurrence(now, "America/New_York", 0, time(9, 0)) == datetime(
        2027, 3, 15, 13, 0, tzinfo=timezone.utc
    )
