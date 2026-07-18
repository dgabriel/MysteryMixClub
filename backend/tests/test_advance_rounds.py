"""Tests for the deadline force-advance job (MYS-145 / MYS-162).

Exercises ``app.jobs.advance_rounds.advance_due_rounds`` directly against the test
DB, one branch of the five-branch state machine per group, plus the deadline copy
and the shared unsubscribe footer/headers on the job's synchronous send path.

The job reaches the database through ``app.db.session.async_session_factory`` (it
has no request / ``get_db`` override), so each test monkeypatches that factory to
the function-scoped test ``session_factory`` — same engine, same event loop,
``expire_on_commit=False`` as the job expects. Emails are captured with the shared
``email_spy`` (SpyEmailSender): ``sends`` is (to, subject, html), ``sent_headers``
is the parallel per-send header dict.

MissingGreenlet trap: primary keys are captured into locals before any
``expire_all`` / re-fetch.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.jobs.advance_rounds import advance_due_rounds
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote
from app.services.notifications import _format_deadline, _subject_and_body


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


@pytest.fixture
def run_job(monkeypatch, session_factory, email_spy):
    """Return an async runner for the job, wired to the test DB + spy sender."""
    monkeypatch.setattr("app.jobs.advance_rounds.async_session_factory", session_factory)
    settings = get_settings()

    async def _run(now: datetime):
        return await advance_due_rounds(now=now, settings=settings, sender=email_spy)

    return _run


async def _seed_user(db_session, email: str, *, notifications: bool = True) -> User:
    user = User(email=email, display_name=email.split("@")[0], email_notifications=notifications)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_league(
    db_session,
    organizer: User,
    *,
    total_rounds: int = 1,
    submission_window_hours: int = 72,
    voting_window_hours: int = 72,
    songs_per_submission: int = 1,
) -> League:
    league = League(
        name="Deadline League",
        organizer_id=organizer.id,
        total_rounds=total_rounds,
        submission_window_hours=submission_window_hours,
        voting_window_hours=voting_window_hours,
        songs_per_submission=songs_per_submission,
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(league)
    return league


async def _add_member(db_session, league_id: uuid.UUID, user: User) -> None:
    db_session.add(LeagueMember(league_id=league_id, user_id=user.id))
    await db_session.commit()


async def _seed_round(
    db_session,
    league_id: uuid.UUID,
    number: int,
    *,
    state: str,
    submission_deadline: datetime | None = None,
    voting_deadline: datetime | None = None,
    submission_opened_at: datetime | None = None,
) -> Round:
    round_ = Round(
        league_id=league_id,
        round_number=number,
        theme=f"round {number}",
        state=state,
        submission_deadline=submission_deadline,
        voting_deadline=voting_deadline,
        submission_opened_at=submission_opened_at,
    )
    db_session.add(round_)
    await db_session.commit()
    await db_session.refresh(round_)
    return round_


async def _seed_submission(
    db_session, round_id: uuid.UUID, user: User, *, mode: str = "playing", title: str = "song"
) -> Submission:
    sub = Submission(
        round_id=round_id,
        user_id=user.id,
        isrc=f"ISRC-{uuid.uuid4()}",
        title=title,
        artist="Artist",
        participation_mode=mode,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _seed_vote(
    db_session, round_id: uuid.UUID, voter: User, submission_id: uuid.UUID
) -> None:
    db_session.add(Vote(round_id=round_id, voter_id=voter.id, submission_id=submission_id))
    await db_session.commit()


def _recipients_for(email_spy, subject_substr: str) -> set[str]:
    return {to for (to, subj, _html) in email_spy.sends if subject_substr in subj}


def _headers_for(email_spy, subject_substr: str) -> dict[str, str] | None:
    for (_to, subj, _html), hdr in zip(email_spy.sends, email_spy.sent_headers):
        if subject_substr in subj:
            return hdr
    return None


def _approx(actual: datetime, expected: datetime, *, tol_seconds: int = 30) -> bool:
    return abs((actual - expected).total_seconds()) < tol_seconds


# ========================================================================== #
# Branch 1 — stamp a NULL deadline (idempotent, no email)
# ========================================================================== #


async def test_branch1_stamps_null_submission_deadline(run_job, db_session, email_spy):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    league = await _seed_league(db_session, org, submission_window_hours=72)
    rnd = await _seed_round(db_session, league.id, 1, state="open_submission")
    rid = rnd.id

    report = await run_job(now)
    assert report.stamped == 1
    assert email_spy.sends == []  # stamping never emails

    db_session.expire_all()
    r = await db_session.get(Round, rid)
    assert r.submission_deadline is not None
    assert _approx(r.submission_deadline, now + timedelta(hours=72))

    # Second run: deadline is now set (72h out), so nothing happens.
    report2 = await run_job(now)
    assert report2.stamped == 0
    assert report2.warned == 0
    assert email_spy.sends == []


async def test_branch1_stamps_null_voting_deadline(run_job, db_session, email_spy):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    league = await _seed_league(db_session, org, voting_window_hours=48)
    rnd = await _seed_round(db_session, league.id, 1, state="open_voting")
    rid = rnd.id

    report = await run_job(now)
    assert report.stamped == 1
    assert email_spy.sends == []

    db_session.expire_all()
    r = await db_session.get(Round, rid)
    assert r.voting_deadline is not None
    assert _approx(r.voting_deadline, now + timedelta(hours=48))


# ========================================================================== #
# Branch 2 — the "about 12 hours left" warning
# ========================================================================== #


async def test_branch2_submission_warning_recipients_and_idempotent(run_job, db_session, email_spy):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")  # member, 0 songs → outstanding
    league = await _seed_league(db_session, org, submission_window_hours=72, songs_per_submission=2)
    partial = await _seed_user(db_session, "partial@e.com")
    complete = await _seed_user(db_session, "complete@e.com")
    optout = await _seed_user(db_session, "optout@e.com", notifications=False)
    for u in (partial, complete, optout):
        await _add_member(db_session, league.id, u)

    rnd = await _seed_round(
        db_session,
        league.id,
        1,
        state="open_submission",
        submission_deadline=now + timedelta(hours=10),
    )
    rid = rnd.id
    await _seed_submission(db_session, rid, partial, title="p1")  # 1 of 2 → partial
    await _seed_submission(db_session, rid, complete, title="c1")
    await _seed_submission(db_session, rid, complete, title="c2")  # 2 of 2 → complete
    await _seed_submission(db_session, rid, optout, title="o1")  # opted out anyway

    report = await run_job(now)
    assert report.warned == 1

    warn = "about 12 hours left to submit"
    # org (0 songs) + partial (1<2) are outstanding; complete (2) done; optout filtered.
    assert _recipients_for(email_spy, warn) == {"o@e.com", "partial@e.com"}

    # Shared footer + one-click headers apply to the job path too (post-refactor).
    html = next(h for (_t, subj, h) in email_spy.sends if warn in subj)
    assert "/api/v1/notifications/unsubscribe?token=" in html
    hdr = _headers_for(email_spy, warn)
    assert hdr is not None
    assert hdr["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "/api/v1/notifications/unsubscribe?token=" in hdr["List-Unsubscribe"]

    db_session.expire_all()
    r = await db_session.get(Round, rid)
    assert r.submission_warning_sent_at is not None

    # Second run: warning already stamped → silent.
    email_spy.sends.clear()
    report2 = await run_job(now)
    assert report2.warned == 0
    assert email_spy.sends == []


async def test_branch2_voting_warning_recipients(run_job, db_session, email_spy):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")  # member, not a submitter → excluded
    league = await _seed_league(db_session, org, voting_window_hours=72)
    playing = await _seed_user(db_session, "playing@e.com")  # playing, not voted → included
    voted = await _seed_user(db_session, "voted@e.com")  # playing, voted → excluded
    viber = await _seed_user(db_session, "viber@e.com")  # vibing → excluded
    optout = await _seed_user(db_session, "optout@e.com", notifications=False)  # excluded
    for u in (playing, voted, viber, optout):
        await _add_member(db_session, league.id, u)

    rnd = await _seed_round(
        db_session,
        league.id,
        1,
        state="open_voting",
        voting_deadline=now + timedelta(hours=10),
    )
    rid = rnd.id
    p_sub = await _seed_submission(db_session, rid, playing, mode="playing", title="p")
    await _seed_submission(db_session, rid, voted, mode="playing", title="v")
    await _seed_submission(db_session, rid, viber, mode="vibing", title="vb")
    await _seed_submission(db_session, rid, optout, mode="playing", title="o")
    # `voted` casts a ballot; `optout` (playing, unvoted) is filtered by notifications.
    await _seed_vote(db_session, rid, voted, p_sub.id)

    report = await run_job(now)
    assert report.warned == 1
    assert _recipients_for(email_spy, "about 12 hours left to vote") == {"playing@e.com"}


async def test_branch2_short_window_never_warns(run_job, db_session, email_spy):
    # An 8h window (≤ 12h) has no "12 hours left" to announce, even inside the window.
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    member = await _seed_user(db_session, "m@e.com")
    league = await _seed_league(db_session, org, submission_window_hours=8)
    await _add_member(db_session, league.id, member)
    await _seed_round(
        db_session,
        league.id,
        1,
        state="open_submission",
        submission_deadline=now + timedelta(hours=4),  # inside the window, 1–12h away
    )

    report = await run_job(now)
    assert report.warned == 0
    assert email_spy.sends == []


async def test_branch2_under_one_hour_is_skipped(run_job, db_session, email_spy):
    # < 1h remaining is past the warning lead window — no warning fires.
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    member = await _seed_user(db_session, "m@e.com")
    league = await _seed_league(db_session, org, submission_window_hours=72)
    await _add_member(db_session, league.id, member)
    await _seed_round(
        db_session,
        league.id,
        1,
        state="open_submission",
        submission_deadline=now + timedelta(minutes=30),
    )

    report = await run_job(now)
    assert report.warned == 0
    assert email_spy.sends == []


# ========================================================================== #
# Branch 3 — empty submission round: notify organizer, never auto-advance
# ========================================================================== #


async def test_branch3_empty_round_notice(run_job, db_session, email_spy):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    member = await _seed_user(db_session, "m@e.com")
    league = await _seed_league(db_session, org, total_rounds=1)
    await _add_member(db_session, league.id, member)
    rnd = await _seed_round(
        db_session,
        league.id,
        1,
        state="open_submission",
        submission_deadline=now - timedelta(hours=1),  # passed
    )
    rid = rnd.id

    report = await run_job(now)
    assert report.empty_notices == 1
    # Organizer only — not the whole league.
    assert _recipients_for(email_spy, "closed with no submissions") == {"o@e.com"}

    db_session.expire_all()
    r = await db_session.get(Round, rid)
    assert r.state == "open_submission"  # NOT advanced — holds open
    assert r.empty_round_notice_sent_at is not None

    # Second run: notice already sent → silent, still not advanced.
    email_spy.sends.clear()
    report2 = await run_job(now)
    assert report2.empty_notices == 0
    assert report2.skipped == 1
    assert email_spy.sends == []


async def test_branch3_empty_round_organizer_optout_still_stamps(run_job, db_session, email_spy):
    # Organizer with notifications off: no email, but the notice is still recorded
    # so repeated runs stay quiet either way.
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com", notifications=False)
    league = await _seed_league(db_session, org, total_rounds=1)
    rnd = await _seed_round(
        db_session,
        league.id,
        1,
        state="open_submission",
        submission_deadline=now - timedelta(hours=1),
    )
    rid = rnd.id

    report = await run_job(now)
    assert report.empty_notices == 1  # branch taken (stamp set)
    assert email_spy.sends == []  # but no email — organizer opted out

    db_session.expire_all()
    r = await db_session.get(Round, rid)
    assert r.empty_round_notice_sent_at is not None
    assert r.state == "open_submission"

    report2 = await run_job(now)
    assert report2.empty_notices == 0
    assert report2.skipped == 1
    assert email_spy.sends == []


# ========================================================================== #
# Branch 4 — passed submission deadline with ≥1 song: force to voting
# ========================================================================== #


async def test_branch4_force_advance_to_voting(run_job, db_session, email_spy):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    m1 = await _seed_user(db_session, "m1@e.com")
    m2 = await _seed_user(db_session, "m2@e.com")
    league = await _seed_league(db_session, org, total_rounds=1, voting_window_hours=72)
    await _add_member(db_session, league.id, m1)
    await _add_member(db_session, league.id, m2)
    rnd = await _seed_round(
        db_session,
        league.id,
        1,
        state="open_submission",
        submission_deadline=now - timedelta(hours=1),  # passed
        submission_opened_at=now - timedelta(hours=73),
    )
    rid = rnd.id
    await _seed_submission(db_session, rid, m1, title="one")  # 1 of 3 members

    report = await run_job(now)
    assert report.advanced_to_voting == 1

    db_session.expire_all()
    r = await db_session.get(Round, rid)
    assert r.state == "open_voting"
    assert r.voting_deadline is not None
    assert _approx(r.voting_deadline, now + timedelta(hours=72), tol_seconds=120)

    # voting_open email to every eligible member (3), with the concrete deadline.
    assert _recipients_for(email_spy, "voting is open") == {"o@e.com", "m1@e.com", "m2@e.com"}
    body = next(h for (_t, subj, h) in email_spy.sends if "voting is open" in subj)
    d = (now + timedelta(hours=72)).astimezone(timezone.utc)
    assert f"Vote by {d.strftime('%b')} {d.day}," in body


# ========================================================================== #
# Branch 4 — Spotify auto-generation on voting_open (MYS-176)
# ========================================================================== #

_SHARED_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000bb")


async def test_branch4_auto_generates_spotify_playlist(
    monkeypatch, session_factory, db_session, email_spy
):
    from app.config import Settings
    from app.models.spotify_connection import SpotifyConnection
    from app.services.spotify_token_crypto import encrypt_refresh_token
    from tests.test_spotify_routes import FakeSpotifyClient

    monkeypatch.setattr("app.jobs.advance_rounds.async_session_factory", session_factory)

    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    league = await _seed_league(db_session, org, total_rounds=1, voting_window_hours=72)
    rnd = await _seed_round(
        db_session,
        league.id,
        1,
        state="open_submission",
        submission_deadline=now - timedelta(hours=1),
        submission_opened_at=now - timedelta(hours=73),
    )
    db_session.add(
        Submission(
            round_id=rnd.id,
            user_id=org.id,
            isrc="ISRC-1",
            title="one",
            artist="Artist",
            participation_mode="playing",
            spotify_track_uri="spotify:track:pre-resolved",
        )
    )
    db_session.add(
        User(id=_SHARED_ACCOUNT_ID, email="playlist-account@example.com", display_name="P")
    )
    await db_session.commit()
    db_session.add(
        SpotifyConnection(
            user_id=_SHARED_ACCOUNT_ID,
            spotify_user_id="spuser",
            refresh_token_encrypted=encrypt_refresh_token("rt"),
            scope="playlist-modify-private",
        )
    )
    await db_session.commit()

    settings = Settings(spotify_playlist_account_user_id=str(_SHARED_ACCOUNT_ID))
    fake = FakeSpotifyClient()

    report = await advance_due_rounds(now=now, settings=settings, sender=email_spy, client=fake)
    assert report.advanced_to_voting == 1
    assert fake.created is not None
    assert fake.created["public"] is True
    assert fake.added == ["spotify:track:pre-resolved"]


async def test_branch4_spotify_failure_does_not_block_advance(
    monkeypatch, session_factory, db_session, email_spy
):
    # A revoked shared-account grant must not prevent the round from advancing
    # or the voting_open email from sending (MYS-176: best-effort).
    from app.config import Settings
    from app.models.spotify_connection import SpotifyConnection
    from app.services.spotify_client import SpotifyAuthError
    from app.services.spotify_token_crypto import encrypt_refresh_token
    from tests.test_spotify_routes import FakeSpotifyClient

    monkeypatch.setattr("app.jobs.advance_rounds.async_session_factory", session_factory)

    class _RejectingClient(FakeSpotifyClient):
        async def refresh_access_token(self, refresh_token):
            raise SpotifyAuthError("invalid_grant")

    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    league = await _seed_league(db_session, org, total_rounds=1, voting_window_hours=72)
    rnd = await _seed_round(
        db_session,
        league.id,
        1,
        state="open_submission",
        submission_deadline=now - timedelta(hours=1),
        submission_opened_at=now - timedelta(hours=73),
    )
    db_session.add(
        Submission(
            round_id=rnd.id,
            user_id=org.id,
            isrc="ISRC-1",
            title="one",
            artist="Artist",
            participation_mode="playing",
        )
    )
    db_session.add(
        User(id=_SHARED_ACCOUNT_ID, email="playlist-account@example.com", display_name="P")
    )
    await db_session.commit()
    db_session.add(
        SpotifyConnection(
            user_id=_SHARED_ACCOUNT_ID,
            spotify_user_id="spuser",
            refresh_token_encrypted=encrypt_refresh_token("rt"),
            scope="playlist-modify-private",
        )
    )
    await db_session.commit()

    settings = Settings(spotify_playlist_account_user_id=str(_SHARED_ACCOUNT_ID))
    report = await advance_due_rounds(
        now=now, settings=settings, sender=email_spy, client=_RejectingClient()
    )
    assert report.advanced_to_voting == 1
    assert report.errors == 0


# ========================================================================== #
# Branch 5 — passed voting deadline: close (zero votes still closes)
# ========================================================================== #


async def test_branch5_close_partial_votes_autoopens_next(run_job, db_session, email_spy):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    m = await _seed_user(db_session, "m@e.com")
    league = await _seed_league(db_session, org, total_rounds=2, submission_window_hours=72)
    await _add_member(db_session, league.id, m)
    r1 = await _seed_round(
        db_session,
        league.id,
        1,
        state="open_voting",
        voting_deadline=now - timedelta(hours=1),  # passed
    )
    r2 = await _seed_round(db_session, league.id, 2, state="pending")
    r1_id, r2_id = r1.id, r2.id
    org_sub = await _seed_submission(db_session, r1_id, org, title="o")
    m_sub = await _seed_submission(db_session, r1_id, m, title="m")
    await _seed_vote(db_session, r1_id, org, m_sub.id)  # partial: only org voted
    _ = org_sub

    report = await run_job(now)
    assert report.closed == 1

    db_session.expire_all()
    closed = await db_session.get(Round, r1_id)
    nxt = await db_session.get(Round, r2_id)
    assert closed.state == "closed"
    # Non-final: the next round auto-opens WITH its own submission deadline stamped.
    assert nxt.state == "open_submission"
    assert nxt.submission_deadline is not None
    assert _approx(nxt.submission_deadline, now + timedelta(hours=72), tol_seconds=120)

    subjects = [subj for (_to, subj, _h) in email_spy.sends]
    assert sum("results are in" in s for s in subjects) == 2  # round_closed × 2 members
    assert sum("open for submissions" in s for s in subjects) == 2  # submission_open × 2


async def test_branch5_zero_votes_still_closes(run_job, db_session, email_spy):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    m = await _seed_user(db_session, "m@e.com")
    league = await _seed_league(db_session, org, total_rounds=2)
    await _add_member(db_session, league.id, m)
    r1 = await _seed_round(
        db_session,
        league.id,
        1,
        state="open_voting",
        voting_deadline=now - timedelta(hours=1),
    )
    r2 = await _seed_round(db_session, league.id, 2, state="pending")
    r1_id = r1.id
    _ = r2
    await _seed_submission(db_session, r1_id, org, title="o")  # a song, but nobody voted

    report = await run_job(now)
    assert report.closed == 1

    db_session.expire_all()
    closed = await db_session.get(Round, r1_id)
    assert closed.state == "closed"


async def test_branch5_final_round_completes_league(run_job, db_session, email_spy):
    now = datetime.now(timezone.utc)
    org = await _seed_user(db_session, "o@e.com")
    m = await _seed_user(db_session, "m@e.com")
    league = await _seed_league(db_session, org, total_rounds=1)  # round 1 is final
    await _add_member(db_session, league.id, m)
    r1 = await _seed_round(
        db_session,
        league.id,
        1,
        state="open_voting",
        voting_deadline=now - timedelta(hours=1),
    )
    r1_id, league_id = r1.id, league.id
    m_sub = await _seed_submission(db_session, r1_id, m, title="m")
    await _seed_vote(db_session, r1_id, org, m_sub.id)

    report = await run_job(now)
    assert report.closed == 1

    db_session.expire_all()
    closed = await db_session.get(Round, r1_id)
    league_after = await db_session.get(League, league_id)
    assert closed.state == "closed"
    assert league_after.state == "complete"

    subjects = [subj for (_to, subj, _h) in email_spy.sends]
    assert sum("results are in" in s for s in subjects) == 2  # round_closed × 2
    assert sum("that's a wrap" in s for s in subjects) == 2  # league_complete × 2


# ========================================================================== #
# Item 6 — _subject_and_body renders / omits the deadline sentence (MYS-162)
# ========================================================================== #


def _mem_league() -> League:
    return League(id=uuid.uuid4(), name="L", organizer_id=uuid.uuid4(), total_rounds=1)


def _mem_round(state: str, **deadlines) -> Round:
    return Round(
        id=uuid.uuid4(),
        league_id=uuid.uuid4(),
        round_number=1,
        theme=None,
        state=state,
        submission_deadline=deadlines.get("submission_deadline"),
        voting_deadline=deadlines.get("voting_deadline"),
    )


def test_subject_body_submission_open_includes_deadline_when_set():
    league = _mem_league()
    deadline = datetime(2026, 7, 5, 21, 0, tzinfo=timezone.utc)
    round_ = _mem_round("open_submission", submission_deadline=deadline)
    _subj, body = _subject_and_body("submission_open", league, round_, "http://x/leagues/1")
    assert f"Submit by {_format_deadline(deadline)}." in body


def test_subject_body_submission_open_omits_deadline_when_none():
    league = _mem_league()
    round_ = _mem_round("open_submission", submission_deadline=None)
    _subj, body = _subject_and_body("submission_open", league, round_, "http://x/leagues/1")
    assert "Submit by" not in body


def test_subject_body_voting_open_includes_deadline_when_set():
    league = _mem_league()
    deadline = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
    round_ = _mem_round("open_voting", voting_deadline=deadline)
    _subj, body = _subject_and_body("voting_open", league, round_, "http://x/leagues/1")
    assert f"Vote by {_format_deadline(deadline)}." in body


def test_subject_body_voting_open_omits_deadline_when_none():
    league = _mem_league()
    round_ = _mem_round("open_voting", voting_deadline=None)
    _subj, body = _subject_and_body("voting_open", league, round_, "http://x/leagues/1")
    assert "Vote by" not in body
