"""Push-notification coverage for the deadline job (MysteryMixClub-4vii.26).

Mirrors test_advance_mixes.py's own seeding helpers/fixture shape exactly
(same `_seed_user`/`_seed_club`/`_seed_mix`/`_seed_submission`/`_seed_vote`,
same `run_job`-style monkeypatch of `async_session_factory`), adding a real
(test-generated) `ApplePushTokenService` and capturing dispatched pushes by
monkeypatching `push_notifications.send_push` itself -- no real APNs network
call, same boundary test_push_notifications.py already draws.

MissingGreenlet trap: primary keys are captured into locals before any
expire_all / re-fetch.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import get_settings
from app.jobs.advance_mixes import advance_due_mixes
from app.services import push_notifications as push_notifications_module
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.device_push_token import DevicePushToken
from app.models.mix import Mix
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote
from app.services.apple_push_token import ApplePushTokenService
from app.services.push_notifications import PushResult

_TEAM_ID = "TEAM123456"
_KEY_ID = "KEY1234567"
_PRIVATE_KEY = (
    ec.generate_private_key(ec.SECP256R1())
    .private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    .decode()
)


@pytest.fixture
def push_calls(monkeypatch):
    """Captures every (device_token, title, body) send_push would have made,
    without any real APNs network call."""
    calls: list[tuple[str, str, str]] = []

    async def fake_send_push(
        client, token_service, bundle_id, device_token, title, body, data=None
    ):
        calls.append((device_token, title, body))
        return PushResult("ok")

    monkeypatch.setattr(push_notifications_module, "send_push", fake_send_push)
    return calls


@pytest.fixture
def run_job(monkeypatch, session_factory, email_spy, push_calls):
    monkeypatch.setattr("app.jobs.advance_mixes.async_session_factory", session_factory)
    settings = get_settings()
    push_token_service = ApplePushTokenService(_TEAM_ID, _KEY_ID, _PRIVATE_KEY)

    async def _run(now: datetime):
        return await advance_due_mixes(
            now=now, settings=settings, sender=email_spy, push_token_service=push_token_service
        )

    return _run


async def _seed_user(
    db_session,
    email: str,
    *,
    push_lifecycle: bool = True,
    push_deadline: bool = True,
    devices: int = 1,
) -> User:
    user = User(
        email=email,
        display_name=email.split("@")[0],
        push_lifecycle_enabled=push_lifecycle,
        push_deadline_reminders_enabled=push_deadline,
    )
    db_session.add(user)
    await db_session.flush()
    for i in range(devices):
        db_session.add(DevicePushToken(user_id=user.id, device_token=f"tok-{user.id}-{i}"))
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_club(db_session, organizer: User, **overrides) -> Club:
    defaults = dict(
        name="Deadline Club",
        organizer_id=organizer.id,
        total_mixes=1,
        submission_window_hours=72,
        voting_window_hours=72,
        songs_per_submission=1,
    )
    defaults.update(overrides)
    club = Club(**defaults)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(club)
    return club


async def _add_member(db_session, club_id: uuid.UUID, user: User) -> None:
    db_session.add(ClubMember(club_id=club_id, user_id=user.id))
    await db_session.commit()


async def _seed_mix(db_session, club_id: uuid.UUID, number: int, **overrides) -> Mix:
    defaults = dict(club_id=club_id, mix_number=number, theme=f"mix {number}")
    defaults.update(overrides)
    mix_ = Mix(**defaults)
    db_session.add(mix_)
    await db_session.commit()
    await db_session.refresh(mix_)
    return mix_


async def _seed_submission(db_session, mix_id, user: User, *, mode: str = "playing") -> Submission:
    sub = Submission(
        mix_id=mix_id,
        user_id=user.id,
        isrc=f"ISRC-{uuid.uuid4()}",
        title="song",
        artist="Artist",
        participation_mode=mode,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _seed_vote(db_session, mix_id, voter: User, submission_id) -> None:
    db_session.add(Vote(mix_id=mix_id, voter_id=voter.id, submission_id=submission_id))
    await db_session.commit()


# --------------------------------------------------------------------------- #
# 1-12h window: push fires alongside email
# --------------------------------------------------------------------------- #


async def test_1_12h_window_sends_push_alongside_email(run_job, db_session, push_calls):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    club = await _seed_club(db_session, org, submission_window_hours=72, songs_per_submission=1)
    rnd = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_deadline=now + timedelta(hours=10),
    )
    rid = rnd.id

    report = await run_job(now)

    assert report.warned == 1
    assert len(push_calls) == 1
    device_token, title, body = push_calls[0]
    assert device_token == f"tok-{org.id}-0"
    assert "About 12 hours left" in body
    db_session.expire_all()
    r = await db_session.get(Mix, rid)
    assert r.submission_warning_sent_at is not None
    # The far (~24h) marker is untouched by the near-window reminder.
    assert r.push_submission_reminder_sent_at is None


# --------------------------------------------------------------------------- #
# ~24h window: push-only far reminder
# --------------------------------------------------------------------------- #


async def test_24h_window_sends_push_only_no_email(run_job, db_session, email_spy, push_calls):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    club = await _seed_club(db_session, org, submission_window_hours=72, songs_per_submission=1)
    rnd = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_deadline=now + timedelta(hours=23, minutes=30),
    )
    rid = rnd.id

    report = await run_job(now)

    assert report.pushed_far == 1
    assert report.warned == 0
    assert email_spy.sends == []  # far reminder is push-only
    assert len(push_calls) == 1
    _device_token, _title, body = push_calls[0]
    assert "About a day left" in body
    db_session.expire_all()
    r = await db_session.get(Mix, rid)
    assert r.push_submission_reminder_sent_at is not None
    assert r.submission_warning_sent_at is None


async def test_24h_reminder_is_idempotent(run_job, db_session, push_calls):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    club = await _seed_club(db_session, org, submission_window_hours=72, songs_per_submission=1)
    await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_deadline=now + timedelta(hours=23, minutes=30),
    )

    await run_job(now)
    push_calls.clear()
    report2 = await run_job(now)

    assert report2.pushed_far == 0
    assert push_calls == []


async def test_short_window_never_sends_the_far_reminder(run_job, db_session, push_calls):
    # A 20h window can never reach the ~24h-out mark at all.
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    club = await _seed_club(db_session, org, submission_window_hours=20, songs_per_submission=1)
    await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_deadline=now + timedelta(hours=18),
    )

    report = await run_job(now)

    assert report.pushed_far == 0
    assert push_calls == []


async def test_voting_phase_24h_reminder_uses_voting_column(run_job, db_session, push_calls):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    club = await _seed_club(db_session, org, voting_window_hours=72)
    playing = await _seed_user(db_session, "playing@e.com")
    await _add_member(db_session, club.id, playing)
    rnd = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_voting",
        voting_deadline=now + timedelta(hours=23, minutes=30),
    )
    mix_id = rnd.id
    await _seed_submission(db_session, mix_id, playing, mode="playing")

    await run_job(now)

    db_session.expire_all()
    r = await db_session.get(Mix, mix_id)
    assert r.push_voting_reminder_sent_at is not None
    assert r.push_submission_reminder_sent_at is None


# --------------------------------------------------------------------------- #
# Preference gating
# --------------------------------------------------------------------------- #


async def test_deadline_reminders_disabled_excludes_from_both_push_windows(
    run_job, db_session, push_calls
):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com", push_deadline=False)
    club = await _seed_club(db_session, org, submission_window_hours=72, songs_per_submission=1)
    await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_deadline=now + timedelta(hours=10),
    )

    report = await run_job(now)

    # Email still fires (email_notifications defaults True, untouched by this
    # push-only preference); push does not.
    assert report.warned == 1
    assert push_calls == []


async def test_deadline_reminders_disabled_does_not_block_lifecycle_push(
    run_job, db_session, push_calls
):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com", push_deadline=False, push_lifecycle=True)
    club = await _seed_club(db_session, org, submission_window_hours=72, songs_per_submission=1)
    rnd = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_deadline=now - timedelta(hours=1),
    )
    await _seed_submission(db_session, rnd.id, org, mode="playing")

    await run_job(now)

    # Branch 4 (advance to voting) is a lifecycle event, gated on
    # push_lifecycle_enabled, independent of push_deadline_reminders_enabled.
    assert any("Voting is open" in body for _t, _title, body in push_calls)


# --------------------------------------------------------------------------- #
# Lifecycle events (branches 4/5) also push
# --------------------------------------------------------------------------- #


async def test_branch4_advance_to_voting_sends_lifecycle_push(run_job, db_session, push_calls):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    club = await _seed_club(db_session, org, submission_window_hours=72, songs_per_submission=1)
    rnd = await _seed_mix(
        db_session,
        club.id,
        1,
        state="open_submission",
        submission_deadline=now - timedelta(hours=1),
    )
    await _seed_submission(db_session, rnd.id, org, mode="playing")

    report = await run_job(now)

    assert report.advanced_to_voting == 1
    assert any("Voting is open" in body for _t, _title, body in push_calls)


async def test_branch5_close_sends_lifecycle_push(run_job, db_session, push_calls):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    club = await _seed_club(db_session, org, voting_window_hours=72)
    await _seed_mix(
        db_session, club.id, 1, state="open_voting", voting_deadline=now - timedelta(hours=1)
    )

    report = await run_job(now)

    assert report.closed == 1
    assert any("results are in" in body for _t, _title, body in push_calls)
