# ruff: noqa: F811  (imported pytest fixtures are redefined as test arguments)
"""The three push-only nudges in the deadline job (MysteryMixClub-bfqo):
halfway, 8am on the due day, and "3 or fewer haven't submitted".

Reuses test_advance_mixes_push.py's seeding helpers and its `run_job` /
`push_calls` fixtures. Every test pins `now`, because the rules are about the
clock (8am in the club's timezone), not about "some time from now".
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.mix import Mix
from tests.test_advance_mixes_push import (  # noqa: F401
    _add_member,
    _seed_club,
    _seed_mix,
    _seed_submission,
    _seed_user,
    _seed_vote,
    push_calls,
    run_job,
)

UTC = timezone.utc
# 10:30 UTC on Tuesday 10 March 2026 (New York is on EDT, UTC-4, since the 8th).
NOW = datetime(2026, 3, 10, 10, 30, tzinfo=UTC)


async def _club_of(db_session, n: int, **club_overrides):
    """A club of `n` members; returns (club, [users]) with the organizer first."""
    users = [await _seed_user(db_session, f"u{i}@e.com") for i in range(n)]
    club = await _seed_club(db_session, users[0], **club_overrides)
    for u in users[1:]:
        await _add_member(db_session, club.id, u)
    return club, users


def _tokens(users) -> set[str]:
    return {f"tok-{u.id}-0" for u in users}


def _sent_tokens(push_calls) -> set[str]:
    return {token for token, _title, _body in push_calls}


def _bodies(push_calls) -> list[str]:
    return [body for _token, _title, body in push_calls]


async def _reload(db_session, mix_id) -> Mix:
    db_session.expire_all()
    return await db_session.get(Mix, mix_id)


# --------------------------------------------------------------------------- #
# Halfway
# --------------------------------------------------------------------------- #


async def _halfway_submission_mix(db_session, club, **overrides):
    # 72h window, exactly half gone: opened 36h ago, due in 36h. The 12h and
    # ~24h reminders and the 8am-on-the-due-day nudge are all hours away.
    fields = dict(
        state="open_submission",
        submission_opened_at=NOW - timedelta(hours=36),
        submission_deadline=NOW + timedelta(hours=36),
    )
    fields.update(overrides)
    return await _seed_mix(db_session, club.id, 1, **fields)


async def test_halfway_goes_only_to_people_who_still_need_to_act(run_job, db_session, push_calls):
    club, users = await _club_of(db_session, 6, submission_window_hours=72)
    mix_ = await _halfway_submission_mix(db_session, club)
    mid = mix_.id
    await _seed_submission(db_session, mid, users[0])
    await _seed_submission(db_session, mid, users[1])

    report = await run_job(NOW)

    assert report.nudged == 1
    assert _sent_tokens(push_calls) == _tokens(users[2:])
    assert _bodies(push_calls) == ["Half the time is gone to submit to Mystery Mix 1: mix 1."] * 4
    assert (await _reload(db_session, mid)).push_submission_halfway_sent_at is not None


async def test_halfway_fires_once(run_job, db_session, push_calls):
    club, users = await _club_of(db_session, 6, submission_window_hours=72)
    await _halfway_submission_mix(db_session, club)

    await run_job(NOW)
    push_calls.clear()
    report = await run_job(NOW + timedelta(minutes=15))

    assert report.nudged == 0
    assert push_calls == []


async def test_halfway_respects_the_push_reminders_toggle(run_job, db_session, push_calls):
    users = [await _seed_user(db_session, f"u{i}@e.com", push_deadline=(i != 3)) for i in range(6)]
    club = await _seed_club(db_session, users[0], submission_window_hours=72)
    for u in users[1:]:
        await _add_member(db_session, club.id, u)
    await _halfway_submission_mix(db_session, club)

    await run_job(NOW)

    assert _sent_tokens(push_calls) == _tokens([u for i, u in enumerate(users) if i != 3])


async def test_halfway_that_lapsed_is_dropped_not_sent_late(run_job, db_session, push_calls):
    club, users = await _club_of(db_session, 6, submission_window_hours=72)
    mix_ = await _halfway_submission_mix(db_session, club)

    # Two hours past the midpoint (a job outage, or the first run after a deploy).
    report = await run_job(NOW + timedelta(hours=2))

    assert report.nudged == 0
    assert push_calls == []
    assert (await _reload(db_session, mix_.id)).push_submission_halfway_sent_at is None


async def test_halfway_is_not_sent_before_the_midpoint(run_job, db_session, push_calls):
    club, users = await _club_of(db_session, 6, submission_window_hours=72)
    await _halfway_submission_mix(db_session, club)

    report = await run_job(NOW - timedelta(minutes=1))

    assert report.nudged == 0
    assert push_calls == []


async def test_halfway_is_suppressed_when_it_lands_on_the_12h_warning(
    run_job, db_session, push_calls
):
    # A 24h phase: its midpoint IS 12 hours before the deadline. Only the
    # established warning goes out.
    club, users = await _club_of(db_session, 6, submission_window_hours=24)
    mix_ = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_opened_at=NOW - timedelta(hours=12),
        submission_deadline=NOW + timedelta(hours=12),
    )

    first = await run_job(NOW)
    second = await run_job(NOW + timedelta(minutes=15))

    assert first.warned == 1
    assert second.nudged == 0
    assert len(push_calls) == 6  # the warning only, once
    assert all("About 12 hours left" in body for body in _bodies(push_calls))
    # ...and the suppressed halfway is retired, so it cannot fire late.
    assert (await _reload(db_session, mix_.id)).push_submission_halfway_sent_at is not None


async def test_halfway_is_suppressed_when_it_lands_on_the_24h_push(run_job, db_session, push_calls):
    # A 48h phase: midpoint is 24h before the deadline.
    club, users = await _club_of(db_session, 6, submission_window_hours=48)
    mix_ = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_opened_at=NOW - timedelta(hours=24),
        submission_deadline=NOW + timedelta(hours=24),
    )

    first = await run_job(NOW)
    second = await run_job(NOW + timedelta(minutes=15))

    assert first.pushed_far == 1
    assert second.nudged == 0
    assert all("About a day left" in body for body in _bodies(push_calls))
    assert len(push_calls) == 6
    assert (await _reload(db_session, mix_.id)).push_submission_halfway_sent_at is not None


async def test_voting_halfway_goes_to_playing_submitters_who_have_not_voted(
    run_job, db_session, push_calls
):
    club, users = await _club_of(db_session, 4, voting_window_hours=72)
    mix_ = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_voting",
        voting_opened_at=NOW - timedelta(hours=36),
        voting_deadline=NOW + timedelta(hours=36),
    )
    subs = [await _seed_submission(db_session, mix_.id, u) for u in users[:3]]
    await _seed_vote(db_session, mix_.id, users[0], subs[1].id)

    report = await run_job(NOW)

    assert report.nudged == 1
    # users[3] never submitted, users[0] already voted.
    assert _sent_tokens(push_calls) == _tokens(users[1:3])
    assert _bodies(push_calls) == ["Half the time is gone to vote in Mystery Mix 1: mix 1."] * 2
    assert (await _reload(db_session, mix_.id)).push_voting_halfway_sent_at is not None


async def test_voting_halfway_needs_to_know_when_voting_opened(run_job, db_session, push_calls):
    # A mix already voting when the column shipped has voting_opened_at NULL.
    club, users = await _club_of(db_session, 4, voting_window_hours=72)
    mix_ = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_voting",
        voting_deadline=NOW + timedelta(hours=36),
    )
    for u in users:
        await _seed_submission(db_session, mix_.id, u)

    report = await run_job(NOW)

    assert report.nudged == 0
    assert push_calls == []


async def test_a_weekly_anchor_club_gets_halfway_from_the_real_phase_stamps(
    run_job, db_session, push_calls
):
    # The configured window (24h) is irrelevant: the phase really ran 4 days.
    club, users = await _club_of(db_session, 6, submission_window_hours=24)
    await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_opened_at=NOW - timedelta(days=2),
        submission_deadline=NOW + timedelta(days=2),
    )

    report = await run_job(NOW)

    assert report.nudged == 1
    assert len(push_calls) == 6


# --------------------------------------------------------------------------- #
# 8am on the due day
# --------------------------------------------------------------------------- #

# 8am in New York on 10 March 2026 is 12:00 UTC; the club is due at 6pm there.
EIGHT_AM_NY = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
SIX_PM_NY = datetime(2026, 3, 10, 22, 0, tzinfo=UTC)


async def _due_today_mix(db_session, club, **overrides):
    # 48h phase; the other reminders and halfway are long behind (or marked).
    fields = dict(
        state="open_submission",
        submission_opened_at=SIX_PM_NY - timedelta(hours=48),
        submission_deadline=SIX_PM_NY,
        submission_warning_sent_at=EIGHT_AM_NY - timedelta(hours=1),
        push_submission_reminder_sent_at=EIGHT_AM_NY - timedelta(hours=20),
        push_submission_halfway_sent_at=EIGHT_AM_NY - timedelta(hours=14),
        push_submission_last_few_sent_at=EIGHT_AM_NY - timedelta(hours=5),
    )
    fields.update(overrides)
    return await _seed_mix(db_session, club.id, 1, **fields)


async def test_due_morning_goes_at_8am_club_time_to_those_who_have_not_submitted(
    run_job, db_session, push_calls
):
    club, users = await _club_of(
        db_session,
        5,
        submission_window_hours=48,
        timezone="America/New_York",
        deadline_mode="weekly_anchor",
    )
    mix_ = await _due_today_mix(db_session, club)
    await _seed_submission(db_session, mix_.id, users[0])

    report = await run_job(EIGHT_AM_NY)

    assert report.nudged == 1
    assert _sent_tokens(push_calls) == _tokens(users[1:])
    assert _bodies(push_calls) == ["Due today: submit to Mystery Mix 1: mix 1."] * 4
    assert (await _reload(db_session, mix_.id)).push_submission_due_morning_sent_at is not None


async def test_due_morning_is_not_sent_before_8am_club_time(run_job, db_session, push_calls):
    club, users = await _club_of(
        db_session,
        5,
        submission_window_hours=48,
        timezone="America/New_York",
        deadline_mode="weekly_anchor",
    )
    await _due_today_mix(db_session, club)

    report = await run_job(EIGHT_AM_NY - timedelta(minutes=15))

    assert report.nudged == 0
    assert push_calls == []


async def test_due_morning_follows_the_club_timezone_not_utc(run_job, db_session, push_calls):
    # The same instant, 12:00 UTC, is well past 8am in a UTC club (its due-day
    # 8am was four hours ago, beyond the grace), so a UTC club hears nothing.
    club, users = await _club_of(
        db_session, 5, submission_window_hours=48, timezone="UTC", deadline_mode="weekly_anchor"
    )
    await _due_today_mix(db_session, club)

    report = await run_job(EIGHT_AM_NY)

    assert report.nudged == 0
    assert push_calls == []


async def test_due_morning_fires_once(run_job, db_session, push_calls):
    club, users = await _club_of(
        db_session,
        5,
        submission_window_hours=48,
        timezone="America/New_York",
        deadline_mode="weekly_anchor",
    )
    await _due_today_mix(db_session, club)

    await run_job(EIGHT_AM_NY)
    push_calls.clear()
    report = await run_job(EIGHT_AM_NY + timedelta(minutes=15))

    assert report.nudged == 0
    assert push_calls == []


async def test_due_morning_skipped_when_the_phase_opened_after_8am_that_day(
    run_job, db_session, push_calls
):
    # Opened at 8:30am, run at 8:45am: inside the grace window of an 8am moment
    # that the phase has already missed, so only the "opened before 8am" rule
    # keeps it quiet.
    club, users = await _club_of(
        db_session,
        5,
        submission_window_hours=8,
        timezone="America/New_York",
        deadline_mode="weekly_anchor",
    )
    await _due_today_mix(
        db_session,
        club,
        submission_opened_at=EIGHT_AM_NY + timedelta(minutes=30),
        submission_warning_sent_at=None,
        push_submission_reminder_sent_at=None,
    )

    report = await run_job(EIGHT_AM_NY + timedelta(minutes=45))

    assert report.nudged == 0
    assert push_calls == []


# 8am and 6pm in Chicago on 10 March 2026 (CDT, UTC-5 since the 8th).
EIGHT_AM_CT = datetime(2026, 3, 10, 13, 0, tzinfo=UTC)
SIX_PM_CT = datetime(2026, 3, 10, 23, 0, tzinfo=UTC)


async def _duration_club_due_today(db_session, **club_overrides):
    club, users = await _club_of(
        db_session, 5, submission_window_hours=48, deadline_mode="duration", **club_overrides
    )
    mix_ = await _due_today_mix(
        db_session,
        club,
        submission_opened_at=SIX_PM_CT - timedelta(hours=48),
        submission_deadline=SIX_PM_CT,
        submission_warning_sent_at=EIGHT_AM_CT - timedelta(hours=1),
        push_submission_reminder_sent_at=EIGHT_AM_CT - timedelta(hours=20),
        push_submission_halfway_sent_at=EIGHT_AM_CT - timedelta(hours=14),
        push_submission_last_few_sent_at=EIGHT_AM_CT - timedelta(hours=5),
    )
    return club, users, mix_


async def test_a_club_with_no_chosen_timezone_gets_due_today_at_8am_us_central(
    run_job, db_session, push_calls
):
    # Duration mode: the stored timezone is the unchosen "UTC" placeholder.
    club, users, mix_ = await _duration_club_due_today(db_session)

    early = await run_job(EIGHT_AM_CT - timedelta(minutes=15))
    assert early.nudged == 0
    assert push_calls == []

    report = await run_job(EIGHT_AM_CT)

    assert report.nudged == 1
    assert _sent_tokens(push_calls) == _tokens(users)
    assert set(_bodies(push_calls)) == {"Due today: submit to Mystery Mix 1: mix 1."}
    assert (await _reload(db_session, mix_.id)).push_submission_due_morning_sent_at is not None


async def test_the_us_central_default_ignores_a_duration_clubs_stored_timezone(
    run_job, db_session, push_calls
):
    # Only a weekly-anchor club's timezone is trusted; this stored value is
    # whatever the API defaulted or an old client sent.
    club, users, mix_ = await _duration_club_due_today(db_session, timezone="Asia/Tokyo")

    report = await run_job(EIGHT_AM_CT)

    assert report.nudged == 1
    assert set(_bodies(push_calls)) == {"Due today: submit to Mystery Mix 1: mix 1."}


async def test_a_weekly_anchor_club_that_chose_utc_gets_8am_utc_not_central(
    run_job, db_session, push_calls
):
    # The fallback keys on the deadline mode, not on the value "UTC": a club that
    # really chose UTC is due at 08:00 UTC (a Central fallback would be 13:00).
    eight_am_utc = datetime(2026, 3, 10, 8, 0, tzinfo=UTC)
    deadline = datetime(2026, 3, 10, 18, 0, tzinfo=UTC)
    club, users = await _club_of(
        db_session, 5, submission_window_hours=48, timezone="UTC", deadline_mode="weekly_anchor"
    )
    await _due_today_mix(
        db_session,
        club,
        submission_opened_at=deadline - timedelta(hours=48),
        submission_deadline=deadline,
        submission_warning_sent_at=eight_am_utc - timedelta(hours=1),
        push_submission_reminder_sent_at=eight_am_utc - timedelta(hours=20),
        push_submission_halfway_sent_at=eight_am_utc - timedelta(hours=14),
        push_submission_last_few_sent_at=eight_am_utc - timedelta(hours=5),
    )

    assert (await run_job(eight_am_utc - timedelta(minutes=15))).nudged == 0
    assert (await run_job(eight_am_utc)).nudged == 1


async def test_the_us_central_default_follows_daylight_saving(run_job, db_session, push_calls):
    # Before the US change (7 March) Chicago is UTC-6, so 8am is 14:00 UTC.
    deadline = datetime(2026, 3, 7, 23, 0, tzinfo=UTC)
    eight_am = datetime(2026, 3, 7, 14, 0, tzinfo=UTC)
    club, users = await _club_of(
        db_session, 5, submission_window_hours=48, deadline_mode="duration"
    )
    await _due_today_mix(
        db_session,
        club,
        submission_opened_at=deadline - timedelta(hours=48),
        submission_deadline=deadline,
        submission_warning_sent_at=eight_am - timedelta(hours=1),
        push_submission_reminder_sent_at=eight_am - timedelta(hours=20),
        push_submission_halfway_sent_at=eight_am - timedelta(hours=14),
        push_submission_last_few_sent_at=eight_am - timedelta(hours=5),
    )

    assert (await run_job(eight_am - timedelta(minutes=15))).nudged == 0
    assert (await run_job(eight_am)).nudged == 1


async def test_due_morning_is_suppressed_when_it_lands_on_the_12h_warning(
    run_job, db_session, push_calls
):
    # Due 8pm New York: 8am is exactly 12 hours before, the warning's moment.
    eight_pm = datetime(2026, 3, 11, 0, 0, tzinfo=UTC)
    club, users = await _club_of(
        db_session,
        5,
        submission_window_hours=48,
        timezone="America/New_York",
        deadline_mode="weekly_anchor",
    )
    mix_ = await _due_today_mix(
        db_session,
        club,
        submission_opened_at=eight_pm - timedelta(hours=48),
        submission_deadline=eight_pm,
        submission_warning_sent_at=EIGHT_AM_NY,
    )

    report = await run_job(EIGHT_AM_NY + timedelta(minutes=15))

    assert report.nudged == 0
    assert push_calls == []
    assert (await _reload(db_session, mix_.id)).push_submission_due_morning_sent_at is not None


async def test_halfway_is_suppressed_when_it_lands_on_the_due_morning_nudge(
    run_job, db_session, push_calls
):
    # A 12h phase from 2am to 2pm New York: its midpoint is 8am, the same
    # moment as "due today". One push, not two.
    club, users = await _club_of(
        db_session,
        5,
        submission_window_hours=12,
        timezone="America/New_York",
        deadline_mode="weekly_anchor",
    )
    mix_ = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_opened_at=EIGHT_AM_NY - timedelta(hours=6),
        submission_deadline=EIGHT_AM_NY + timedelta(hours=6),
    )

    first = await run_job(EIGHT_AM_NY)
    second = await run_job(EIGHT_AM_NY + timedelta(minutes=15))

    assert first.nudged == 1
    assert second.nudged == 0
    assert set(_bodies(push_calls)) == {"Due today: submit to Mystery Mix 1: mix 1."}
    assert len(push_calls) == 5
    assert (await _reload(db_session, mix_.id)).push_submission_halfway_sent_at is not None


async def test_voting_due_morning_goes_to_submitters_who_have_not_voted(
    run_job, db_session, push_calls
):
    club, users = await _club_of(
        db_session,
        4,
        voting_window_hours=48,
        timezone="America/New_York",
        deadline_mode="weekly_anchor",
    )
    mix_ = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_voting",
        voting_opened_at=SIX_PM_NY - timedelta(hours=48),
        voting_deadline=SIX_PM_NY,
        voting_warning_sent_at=EIGHT_AM_NY - timedelta(hours=1),
        push_voting_reminder_sent_at=EIGHT_AM_NY - timedelta(hours=20),
        push_voting_halfway_sent_at=EIGHT_AM_NY - timedelta(hours=14),
    )
    subs = [await _seed_submission(db_session, mix_.id, u) for u in users]
    await _seed_vote(db_session, mix_.id, users[0], subs[1].id)

    report = await run_job(EIGHT_AM_NY)

    assert report.nudged == 1
    assert _sent_tokens(push_calls) == _tokens(users[1:])
    assert _bodies(push_calls) == ["Due today: vote in Mystery Mix 1: mix 1."] * 3
    assert (await _reload(db_session, mix_.id)).push_voting_due_morning_sent_at is not None


# --------------------------------------------------------------------------- #
# 3 or fewer haven't submitted
# --------------------------------------------------------------------------- #


async def _fresh_submission_mix(db_session, club):
    # Opened an hour ago, due in ~47h: no time-based nudge is anywhere near.
    return await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_opened_at=NOW - timedelta(hours=1),
        submission_deadline=NOW + timedelta(hours=47),
    )


async def test_last_few_goes_only_to_the_people_who_have_not_submitted(
    run_job, db_session, push_calls
):
    club, users = await _club_of(db_session, 6, submission_window_hours=48)
    mix_ = await _fresh_submission_mix(db_session, club)
    for u in users[:3]:
        await _seed_submission(db_session, mix_.id, u)

    report = await run_job(NOW)

    assert report.nudged == 1
    assert _sent_tokens(push_calls) == _tokens(users[3:])
    assert (
        _bodies(push_calls)
        == ["Only 3 people, including you, still need to submit to Mystery Mix 1: mix 1."] * 3
    )
    assert (await _reload(db_session, mix_.id)).push_submission_last_few_sent_at is not None


async def test_last_few_copy_never_names_anyone_and_counts_the_remaining(
    run_job, db_session, push_calls
):
    club, users = await _club_of(db_session, 6, submission_window_hours=48)
    mix_ = await _fresh_submission_mix(db_session, club)
    for u in users[:4]:
        await _seed_submission(db_session, mix_.id, u)

    await run_job(NOW)

    assert set(_bodies(push_calls)) == {
        "Only 2 people, including you, still need to submit to Mystery Mix 1: mix 1."
    }
    for u in users:
        assert all(u.display_name not in body for body in _bodies(push_calls))


async def test_last_few_with_one_person_left_tells_only_them(run_job, db_session, push_calls):
    club, users = await _club_of(db_session, 5, submission_window_hours=48)
    mix_ = await _fresh_submission_mix(db_session, club)
    for u in users[:4]:
        await _seed_submission(db_session, mix_.id, u)

    await run_job(NOW)

    assert _sent_tokens(push_calls) == _tokens(users[4:])
    assert _bodies(push_calls) == ["Only you still need to submit to Mystery Mix 1: mix 1."]


async def test_last_few_stays_quiet_while_more_than_three_are_outstanding(
    run_job, db_session, push_calls
):
    club, users = await _club_of(db_session, 6, submission_window_hours=48)
    mix_ = await _fresh_submission_mix(db_session, club)
    for u in users[:2]:
        await _seed_submission(db_session, mix_.id, u)

    report = await run_job(NOW)

    assert report.nudged == 0
    assert push_calls == []


async def test_last_few_stays_quiet_when_nobody_has_submitted_yet(run_job, db_session, push_calls):
    # A three-member club where nothing is in yet: "3 left" is just everyone.
    club, users = await _club_of(db_session, 3, submission_window_hours=48)
    mix_ = await _fresh_submission_mix(db_session, club)

    report = await run_job(NOW)

    assert report.nudged == 0
    assert push_calls == []
    assert (await _reload(db_session, mix_.id)).push_submission_last_few_sent_at is None


async def test_last_few_fires_once_per_mix(run_job, db_session, push_calls):
    club, users = await _club_of(db_session, 6, submission_window_hours=48)
    mix_ = await _fresh_submission_mix(db_session, club)
    for u in users[:3]:
        await _seed_submission(db_session, mix_.id, u)

    await run_job(NOW)
    await _seed_submission(db_session, mix_.id, users[3])  # 2 left now
    push_calls.clear()
    report = await run_job(NOW + timedelta(minutes=15))

    assert report.nudged == 0
    assert push_calls == []


async def test_last_few_respects_the_push_reminders_toggle(run_job, db_session, push_calls):
    users = [await _seed_user(db_session, f"u{i}@e.com", push_deadline=(i != 4)) for i in range(6)]
    club = await _seed_club(db_session, users[0], submission_window_hours=48)
    for u in users[1:]:
        await _add_member(db_session, club.id, u)
    mix_ = await _fresh_submission_mix(db_session, club)
    for u in users[:3]:
        await _seed_submission(db_session, mix_.id, u)

    await run_job(NOW)

    # users[4] opted out of reminders; the other two outstanding members get it,
    # and the count still tells the truth (3 people remain).
    assert _sent_tokens(push_calls) == _tokens([users[3], users[5]])
    assert set(_bodies(push_calls)) == {
        "Only 3 people, including you, still need to submit to Mystery Mix 1: mix 1."
    }


async def test_last_few_is_a_submission_phase_notice_only(run_job, db_session, push_calls):
    club, users = await _club_of(db_session, 5, voting_window_hours=48)
    mix_ = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_voting",
        voting_opened_at=NOW - timedelta(hours=1),
        voting_deadline=NOW + timedelta(hours=47),
    )
    subs = [await _seed_submission(db_session, mix_.id, u) for u in users]
    for u in users[:3]:
        await _seed_vote(db_session, mix_.id, u, subs[4].id)

    report = await run_job(NOW)

    assert report.nudged == 0
    assert push_calls == []


# --------------------------------------------------------------------------- #
# One nudge per run
# --------------------------------------------------------------------------- #


async def test_only_one_nudge_goes_out_per_run(run_job, db_session, push_calls):
    # Due morning and last-few are both due at once: due morning first, and the
    # last-few follows on the next pass rather than stacking on the same phone.
    club, users = await _club_of(
        db_session,
        5,
        submission_window_hours=48,
        timezone="America/New_York",
        deadline_mode="weekly_anchor",
    )
    mix_ = await _due_today_mix(db_session, club, push_submission_last_few_sent_at=None)
    for u in users[:3]:
        await _seed_submission(db_session, mix_.id, u)

    first = await run_job(EIGHT_AM_NY)
    assert first.nudged == 1
    assert set(_bodies(push_calls)) == {"Due today: submit to Mystery Mix 1: mix 1."}

    push_calls.clear()
    second = await run_job(EIGHT_AM_NY + timedelta(minutes=15))
    assert second.nudged == 1
    assert set(_bodies(push_calls)) == {
        "Only 2 people, including you, still need to submit to Mystery Mix 1: mix 1."
    }


# --------------------------------------------------------------------------- #
# Stamps
# --------------------------------------------------------------------------- #


async def test_advancing_to_voting_stamps_when_voting_opened(run_job, db_session, push_calls):
    club, users = await _club_of(db_session, 2, submission_window_hours=48)
    mix_ = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_opened_at=NOW - timedelta(hours=49),
        submission_deadline=NOW - timedelta(minutes=1),
    )
    mid = mix_.id
    await _seed_submission(db_session, mid, users[0])

    report = await run_job(NOW)

    assert report.advanced_to_voting == 1
    assert (await _reload(db_session, mid)).voting_opened_at is not None
    assert (await db_session.scalars(select(Mix).where(Mix.id == mid))).one().state == "open_voting"


# --------------------------------------------------------------------------- #
# Review fixes: audiences, suppression against what really fires
# --------------------------------------------------------------------------- #


async def test_halfway_reaches_members_with_email_off(run_job, db_session, push_calls):
    club, users = await _club_of(db_session, 6, submission_window_hours=72)
    for u in users[2:4]:
        u.email_notifications = False
    await db_session.commit()
    mix_ = await _halfway_submission_mix(db_session, club)
    for u in users[:2]:
        await _seed_submission(db_session, mix_.id, u)

    await run_job(NOW)

    assert _sent_tokens(push_calls) == _tokens(users[2:])


async def test_last_few_stays_quiet_when_email_off_members_make_it_four(
    run_job, db_session, push_calls
):
    # 6 members, 2 submitted, 2 of the other 4 have email off: four are
    # outstanding, so no "last few", even though only 2 have email on.
    club, users = await _club_of(db_session, 6, submission_window_hours=48)
    for u in users[2:4]:
        u.email_notifications = False
    await db_session.commit()
    mix_ = await _fresh_submission_mix(db_session, club)
    for u in users[:2]:
        await _seed_submission(db_session, mix_.id, u)

    report = await run_job(NOW)

    assert report.nudged == 0
    assert push_calls == []


async def test_last_few_counts_email_off_members_and_reaches_them(run_job, db_session, push_calls):
    club, users = await _club_of(db_session, 6, submission_window_hours=48)
    users[4].email_notifications = False
    await db_session.commit()
    mix_ = await _fresh_submission_mix(db_session, club)
    for u in users[:3]:
        await _seed_submission(db_session, mix_.id, u)

    await run_job(NOW)

    assert _sent_tokens(push_calls) == _tokens(users[3:])
    assert set(_bodies(push_calls)) == {
        "Only 3 people, including you, still need to submit to Mystery Mix 1: mix 1."
    }


async def test_a_nudge_with_nobody_to_notify_is_still_retired(run_job, db_session, push_calls):
    users = [await _seed_user(db_session, f"u{i}@e.com", push_deadline=False) for i in range(6)]
    club = await _seed_club(db_session, users[0], submission_window_hours=72)
    for u in users[1:]:
        await _add_member(db_session, club.id, u)
    mix_ = await _halfway_submission_mix(db_session, club)

    report = await run_job(NOW)

    assert report.nudged == 0
    assert push_calls == []
    assert (await _reload(db_session, mix_.id)).push_submission_halfway_sent_at is not None


async def test_a_phase_shorter_than_the_reminder_lead_still_suppresses_a_nearby_nudge(
    run_job, db_session, push_calls
):
    # A weekly-anchor club configured for 72h whose phase really runs 9h: the
    # 12h warning fires the moment the phase opens (it is already inside 12h).
    # A due-today nudge 30 minutes later must not stack on it.
    club, users = await _club_of(
        db_session,
        5,
        submission_window_hours=72,
        timezone="America/New_York",
        deadline_mode="weekly_anchor",
    )
    opened = EIGHT_AM_NY - timedelta(minutes=30)  # 7:30am
    mix_ = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_opened_at=opened,
        submission_deadline=opened + timedelta(hours=9),
    )

    first = await run_job(opened)
    second = await run_job(EIGHT_AM_NY)

    assert first.warned == 1
    assert second.nudged == 0
    assert len(push_calls) == 5  # the warning only
    assert (await _reload(db_session, mix_.id)).push_submission_due_morning_sent_at is not None


async def test_a_suppressed_due_morning_does_not_also_suppress_halfway(
    run_job, db_session, push_calls
):
    # Halfway 07:01, due-morning 08:00 (suppressed by the 12h warning at 08:50),
    # so halfway is 1h49m from the nearest push that really goes out and sends.
    club, users = await _club_of(
        db_session,
        5,
        submission_window_hours=72,
        timezone="America/New_York",
        deadline_mode="weekly_anchor",
    )
    deadline = EIGHT_AM_NY + timedelta(hours=12, minutes=50)  # 20:50 local
    opened = deadline - timedelta(hours=27, minutes=38)  # midpoint 07:01 local
    mix_ = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_opened_at=opened,
        submission_deadline=deadline,
        push_submission_reminder_sent_at=opened,
    )

    report = await run_job(EIGHT_AM_NY - timedelta(minutes=30))

    assert report.nudged == 1
    assert set(_bodies(push_calls)) == {"Half the time is gone to submit to Mystery Mix 1: mix 1."}
    assert (await _reload(db_session, mix_.id)).push_submission_halfway_sent_at is not None


async def test_a_bad_club_timezone_does_not_silence_the_other_nudges(
    run_job, db_session, push_calls
):
    club, users = await _club_of(
        db_session,
        6,
        submission_window_hours=72,
        timezone="Not/AZone",
        deadline_mode="weekly_anchor",
    )
    await _halfway_submission_mix(db_session, club)

    report = await run_job(NOW)

    assert report.nudged == 1
    assert report.errors == 0
    assert len(push_calls) == 6
