"""Tests for MYS-69: auto-advance round lifecycle.

Voting must be opened manually by the organizer (PATCH state=open_voting).
Auto-advance only fires on the voting side: when every playing submitter has
voted, the round advances open_voting -> closed (auto-opening the next pending
round or completing the league). An all-vibing round chains open_voting -> closed
in the same PATCH request because voting quorum is immediately met (empty playing
set) and vibers never cast votes.

These exercise the shared ``advance_round_state`` helper plus the voting quorum
predicate (``voting_quorum_met``) through the real submit/vote/PATCH endpoints,
and assert the lifecycle notifications fire on the same path. The link assembler
+ YouTube resolver are faked so the suite stays offline; the email sender is the
shared spy so we can assert on the lifecycle emails.

``submission_opened_at`` and ``joined_at`` are set explicitly (fixed timestamps)
so the active-at-open quorum window is deterministic and late joiners / removed
members can be placed precisely relative to it.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.db.session import get_db
from app.main import create_app
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.services.email import get_email_sender
from app.services.song_links import get_link_assembler
from app.services.youtube_resolver import get_youtube_resolver

# Fixed window so the active-at-open quorum set is deterministic: members joined
# BEFORE are in-window, the round opened AT, a late joiner joins AFTER.
OPEN_TIME = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
BEFORE = OPEN_TIME - timedelta(hours=1)
AFTER = OPEN_TIME + timedelta(hours=1)


# --------------------------------------------------------------------------- #
# Fakes + client builder (keep the suite offline; spy the email sender)
# --------------------------------------------------------------------------- #


class _FakeAssembler:
    async def assemble(
        self, title, artist=None, isrc=None, *, youtube_video_id=None
    ) -> dict[str, str]:
        return {"youtube": "https://music.youtube.com/search?q=x"}


class _FakeYouTube:
    async def video_id_for(self, title, artist=None) -> str | None:
        return None


def _build_client(session_factory, email_spy) -> AsyncClient:
    app = create_app()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_email_sender] = lambda: email_spy
    app.dependency_overrides[get_link_assembler] = lambda: _FakeAssembler()
    app.dependency_overrides[get_youtube_resolver] = lambda: _FakeYouTube()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --------------------------------------------------------------------------- #
# Seeding helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str) -> User:
    user = User(email=email, display_name="U")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_submission(
    db_session, round_id: uuid.UUID, user_id: uuid.UUID, *, mode: str = "playing", title="song"
) -> Submission:
    sub = Submission(
        round_id=round_id,
        user_id=user_id,
        isrc="USABC1234567",
        title=title,
        artist="Artist",
        participation_mode=mode,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _body(**over) -> dict:
    title = over.get("title", "bad guy")
    body = {"isrc": f"USABC{abs(hash(title)):07d}", "title": "bad guy", "artist": "Billie Eilish"}
    body.update(over)
    return body


async def _submit(client, round_id, user_id, **over):
    return await client.post(
        f"/api/v1/rounds/{round_id}/submissions", json=_body(**over), headers=_auth(user_id)
    )


async def _cast(client, round_id, user_id, target_ids):
    return await client.post(
        f"/api/v1/rounds/{round_id}/votes",
        json={"submission_ids": [str(t) for t in target_ids]},
        headers=_auth(user_id),
    )


async def _round(db_session, round_id) -> Round:
    db_session.expire_all()
    return await db_session.scalar(select(Round).where(Round.id == round_id))


async def _league(db_session, league_id) -> League:
    db_session.expire_all()
    return await db_session.scalar(select(League).where(League.id == league_id))


def _subjects(email_spy) -> list[str]:
    return [subj for (_to, subj, _html) in email_spy.sends]


# --------------------------------------------------------------------------- #
# Submission does NOT auto-open voting (voting is manual)
# --------------------------------------------------------------------------- #


async def test_last_submit_stays_open_no_auto_advance(session_factory, db_session, email_spy):
    # Scenario 1: all members submit — round stays open_submission. Voting must
    # be opened manually; no voting_open email fires on submit.
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "m@example.com")
    league = League(name="L", organizer_id=organizer.id, total_rounds=1, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id, joined_at=BEFORE))
    db_session.add(LeagueMember(league_id=league.id, user_id=member.id, joined_at=BEFORE))
    round_ = Round(
        league_id=league.id,
        round_number=1,
        theme="t",
        state="open_submission",
        submission_opened_at=OPEN_TIME,
    )
    db_session.add(round_)
    await db_session.commit()
    round_id, org_id, member_id = round_.id, organizer.id, member.id

    async with _build_client(session_factory, email_spy) as client:
        first = await _submit(client, round_id, org_id, title="a")
        assert first.status_code == 201, first.text
        email_spy.sends.clear()
        second = await _submit(client, round_id, member_id, title="b")
        assert second.status_code == 201, second.text

    assert (await _round(db_session, round_id)).state == "open_submission"
    assert not any("voting is open" in s for s in _subjects(email_spy))


async def test_partial_submission_stays_open(session_factory, db_session, email_spy):
    # Scenario 2: with one member still un-submitted, the round stays open.
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "m@example.com")
    league = League(name="L", organizer_id=organizer.id, total_rounds=1, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id, joined_at=BEFORE))
    db_session.add(LeagueMember(league_id=league.id, user_id=member.id, joined_at=BEFORE))
    round_ = Round(
        league_id=league.id,
        round_number=1,
        theme="t",
        state="open_submission",
        submission_opened_at=OPEN_TIME,
    )
    db_session.add(round_)
    await db_session.commit()
    round_id, org_id = round_.id, organizer.id

    async with _build_client(session_factory, email_spy) as client:
        email_spy.sends.clear()
        resp = await _submit(client, round_id, org_id)
        assert resp.status_code == 201, resp.text

    assert (await _round(db_session, round_id)).state == "open_submission"
    assert not any("voting is open" in s for s in _subjects(email_spy))


async def test_late_joiner_can_submit_round_stays_open(session_factory, db_session, email_spy):
    # Scenario 3: a late joiner submitting doesn't trigger any advance — the
    # round stays open_submission regardless of who has submitted.
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "m@example.com")
    latecomer = await _seed_user(db_session, "late@example.com")
    league = League(name="L", organizer_id=organizer.id, total_rounds=1, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id, joined_at=BEFORE))
    db_session.add(LeagueMember(league_id=league.id, user_id=member.id, joined_at=BEFORE))
    db_session.add(LeagueMember(league_id=league.id, user_id=latecomer.id, joined_at=AFTER))
    round_ = Round(
        league_id=league.id,
        round_number=1,
        theme="t",
        state="open_submission",
        submission_opened_at=OPEN_TIME,
    )
    db_session.add(round_)
    await db_session.commit()
    round_id, org_id, member_id = round_.id, organizer.id, member.id

    async with _build_client(session_factory, email_spy) as client:
        await _submit(client, round_id, org_id, title="a")
        await _submit(client, round_id, member_id, title="b")

    assert (await _round(db_session, round_id)).state == "open_submission"


async def test_removed_member_can_submit_round_stays_open(session_factory, db_session, email_spy):
    # Scenario 4: even with a removed member present, all submitting keeps the
    # round in open_submission — no auto-advance on submit.
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "m@example.com")
    gone = await _seed_user(db_session, "gone@example.com")
    league = League(name="L", organizer_id=organizer.id, total_rounds=1, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id, joined_at=BEFORE))
    db_session.add(LeagueMember(league_id=league.id, user_id=member.id, joined_at=BEFORE))
    db_session.add(
        LeagueMember(league_id=league.id, user_id=gone.id, joined_at=BEFORE, removed_at=AFTER)
    )
    round_ = Round(
        league_id=league.id,
        round_number=1,
        theme="t",
        state="open_submission",
        submission_opened_at=OPEN_TIME,
    )
    db_session.add(round_)
    await db_session.commit()
    round_id, org_id, member_id = round_.id, organizer.id, member.id

    async with _build_client(session_factory, email_spy) as client:
        await _submit(client, round_id, org_id, title="a")
        await _submit(client, round_id, member_id, title="b")

    assert (await _round(db_session, round_id)).state == "open_submission"


async def test_viber_submit_round_stays_open(session_factory, db_session, email_spy):
    # Scenario 5: a vibing member submitting doesn't trigger an advance —
    # the round stays open_submission regardless.
    organizer = await _seed_user(db_session, "org@example.com")
    viber = await _seed_user(db_session, "v@example.com")
    league = League(name="L", organizer_id=organizer.id, total_rounds=1, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id, joined_at=BEFORE))
    db_session.add(
        LeagueMember(league_id=league.id, user_id=viber.id, joined_at=BEFORE, vibe_mode=True)
    )
    round_ = Round(
        league_id=league.id,
        round_number=1,
        theme="t",
        state="open_submission",
        submission_opened_at=OPEN_TIME,
    )
    db_session.add(round_)
    await db_session.commit()
    round_id, org_id, viber_id = round_.id, organizer.id, viber.id

    async with _build_client(session_factory, email_spy) as client:
        await _submit(client, round_id, org_id, title="a")
        vibe_resp = await _submit(client, round_id, viber_id, title="b")
        assert vibe_resp.status_code == 201, vibe_resp.text
        assert vibe_resp.json()["participation_mode"] == "vibing"

    assert (await _round(db_session, round_id)).state == "open_submission"


# --------------------------------------------------------------------------- #
# Voting quorum -> auto-close (next round / completion)
# --------------------------------------------------------------------------- #


async def _seed_voting_round(
    db_session, *, n_players: int, total_rounds: int, with_next_pending: bool, viber: bool = False
):
    """Seed a league with round 1 in open_voting, ``n_players`` playing submitters
    (+ optionally one vibing submitter), and optionally a pending round 2."""
    organizer = await _seed_user(db_session, "org@example.com")
    league = League(
        name="L", organizer_id=organizer.id, total_rounds=total_rounds, votes_per_player=3
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id, joined_at=BEFORE))
    round_ = Round(
        league_id=league.id,
        round_number=1,
        theme="t",
        state="open_voting",
        submission_opened_at=OPEN_TIME,
    )
    db_session.add(round_)
    if with_next_pending:
        db_session.add(Round(league_id=league.id, round_number=2, theme="t2", state="pending"))
    await db_session.commit()

    players = [organizer]
    for i in range(n_players - 1):
        p = await _seed_user(db_session, f"p{i}@example.com")
        db_session.add(LeagueMember(league_id=league.id, user_id=p.id, joined_at=BEFORE))
        players.append(p)
    await db_session.commit()

    subs = {}
    for idx, p in enumerate(players):
        s = await _seed_submission(db_session, round_.id, p.id, title=f"play-{idx}")
        subs[p.id] = s.id
    vibe_sub_id = None
    if viber:
        v = await _seed_user(db_session, "vibe@example.com")
        db_session.add(
            LeagueMember(league_id=league.id, user_id=v.id, joined_at=BEFORE, vibe_mode=True)
        )
        await db_session.commit()
        vibe_sub_id = (
            await _seed_submission(db_session, round_.id, v.id, mode="vibing", title="vibe")
        ).id

    return {
        "league_id": league.id,
        "round_id": round_.id,
        "player_ids": [p.id for p in players],
        "subs": subs,
        "vibe_sub_id": vibe_sub_id,
    }


async def test_last_vote_closes_and_opens_next_round(session_factory, db_session, email_spy):
    # Scenario 6: all playing submitters vote -> round closes, next pending round
    # auto-opens, current_round advances, round_closed + submission_open fire.
    seed = await _seed_voting_round(db_session, n_players=3, total_rounds=2, with_next_pending=True)
    round_id, league_id = seed["round_id"], seed["league_id"]
    p = seed["player_ids"]
    subs = seed["subs"]
    round2_id = await db_session.scalar(
        select(Round.id).where(Round.league_id == league_id, Round.round_number == 2)
    )

    async with _build_client(session_factory, email_spy) as client:
        # Each player votes for the next player's song (no self-votes).
        await _cast(client, round_id, p[0], [subs[p[1]]])
        await _cast(client, round_id, p[1], [subs[p[2]]])
        assert (await _round(db_session, round_id)).state == "open_voting"  # not yet

        email_spy.sends.clear()
        last = await _cast(client, round_id, p[2], [subs[p[0]]])
        assert last.status_code == 200, last.text

    assert (await _round(db_session, round_id)).state == "closed"
    assert (await _round(db_session, round2_id)).state == "open_submission"
    assert (await _league(db_session, league_id)).current_round == 2
    subjects = _subjects(email_spy)
    assert any("results are in" in s for s in subjects)
    assert any("open for submissions" in s for s in subjects)


async def test_final_round_voting_completes_league(session_factory, db_session, email_spy):
    # Scenario 7: closing the final round via voting quorum completes the league.
    seed = await _seed_voting_round(
        db_session, n_players=2, total_rounds=1, with_next_pending=False
    )
    round_id, league_id = seed["round_id"], seed["league_id"]
    p = seed["player_ids"]
    subs = seed["subs"]

    async with _build_client(session_factory, email_spy) as client:
        await _cast(client, round_id, p[0], [subs[p[1]]])
        email_spy.sends.clear()
        await _cast(client, round_id, p[1], [subs[p[0]]])

    assert (await _round(db_session, round_id)).state == "closed"
    league = await _league(db_session, league_id)
    assert league.state == "complete"
    assert league.completed_at is not None
    subjects = _subjects(email_spy)
    assert any("results are in" in s for s in subjects)
    assert any("that's a wrap" in s for s in subjects)


async def test_viber_excluded_from_voting_quorum(session_factory, db_session, email_spy):
    # Scenario 8: once all PLAYERS vote, the round closes even though the viber
    # never votes (vibers are excluded from the voting quorum).
    seed = await _seed_voting_round(
        db_session, n_players=2, total_rounds=1, with_next_pending=False, viber=True
    )
    round_id, league_id = seed["round_id"], seed["league_id"]
    p = seed["player_ids"]
    subs = seed["subs"]

    async with _build_client(session_factory, email_spy) as client:
        await _cast(client, round_id, p[0], [subs[p[1]]])
        assert (await _round(db_session, round_id)).state == "open_voting"  # 1 of 2 players
        await _cast(client, round_id, p[1], [subs[p[0]]])

    assert (await _round(db_session, round_id)).state == "closed"
    assert (await _league(db_session, league_id)).state == "complete"


async def test_partial_votes_stay_open(session_factory, db_session, email_spy):
    # Scenario 9: with one playing submitter still un-voted, the round stays open.
    seed = await _seed_voting_round(
        db_session, n_players=3, total_rounds=1, with_next_pending=False
    )
    round_id = seed["round_id"]
    p = seed["player_ids"]
    subs = seed["subs"]

    async with _build_client(session_factory, email_spy) as client:
        email_spy.sends.clear()
        await _cast(client, round_id, p[0], [subs[p[1]]])

    assert (await _round(db_session, round_id)).state == "open_voting"
    assert not any("results are in" in s for s in _subjects(email_spy))


# --------------------------------------------------------------------------- #
# All-vibing round: chain submission -> voting -> closed in one request
# --------------------------------------------------------------------------- #


async def test_all_vibing_round_chains_to_closed(session_factory, db_session, email_spy):
    # Scenario 10: every active member is vibing. Submission stays open until the
    # organizer manually opens voting (PATCH state=open_voting). At that point,
    # voting quorum is immediately met (empty playing set), so the round chains
    # open_voting -> closed in the same request, auto-opening the next round.
    # Vibers never cast votes so the chain must happen at the manual advance, not
    # in cast_votes.
    organizer = await _seed_user(db_session, "org@example.com")
    viber = await _seed_user(db_session, "v@example.com")
    league = League(
        name="L",
        organizer_id=organizer.id,
        total_rounds=2,
        votes_per_player=3,
        default_vibe_mode=True,
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(
        LeagueMember(league_id=league.id, user_id=organizer.id, joined_at=BEFORE, vibe_mode=True)
    )
    db_session.add(
        LeagueMember(league_id=league.id, user_id=viber.id, joined_at=BEFORE, vibe_mode=True)
    )
    round_ = Round(
        league_id=league.id,
        round_number=1,
        theme="t",
        state="open_submission",
        submission_opened_at=OPEN_TIME,
    )
    db_session.add(round_)
    db_session.add(Round(league_id=league.id, round_number=2, theme="t2", state="pending"))
    await db_session.commit()
    round_id, league_id, org_id, viber_id = round_.id, league.id, organizer.id, viber.id
    round2_id = await db_session.scalar(
        select(Round.id).where(Round.league_id == league_id, Round.round_number == 2)
    )

    async with _build_client(session_factory, email_spy) as client:
        await _submit(client, round_id, org_id, title="a")
        await _submit(client, round_id, viber_id, title="b")
        # All submitted, but round must stay open_submission — no auto-advance.
        assert (await _round(db_session, round_id)).state == "open_submission"

        email_spy.sends.clear()
        # Organizer manually opens voting — quorum immediately met, chains to closed.
        resp = await client.patch(
            f"/api/v1/rounds/{round_id}",
            json={"state": "open_voting"},
            headers=_auth(org_id),
        )
        assert resp.status_code == 200, resp.text

    assert (await _round(db_session, round_id)).state == "closed"
    assert (await _round(db_session, round2_id)).state == "open_submission"
    assert (await _league(db_session, league_id)).current_round == 2
    subjects = _subjects(email_spy)
    # voting_open is suppressed — the round closed in the same breath as it opened
    # for voting, so nobody could have voted. Only round_closed + next submission_open.
    assert not any("voting is open" in s for s in subjects)
    assert any("results are in" in s for s in subjects)
    assert any("open for submissions" in s for s in subjects)


# --------------------------------------------------------------------------- #
# Manual override + submission_opened_at stamping (scenarios 11, 12)
# --------------------------------------------------------------------------- #


async def test_manual_advance_still_works_below_quorum(session_factory, db_session, email_spy):
    # Scenario 11: the organizer's manual PATCH advance is unaffected by
    # auto-advance — they can force open_voting even though the submission quorum
    # isn't met (no one submitted).
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "m@example.com")
    league = League(name="L", organizer_id=organizer.id, total_rounds=2, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id, joined_at=BEFORE))
    db_session.add(LeagueMember(league_id=league.id, user_id=member.id, joined_at=BEFORE))
    round_ = Round(
        league_id=league.id,
        round_number=1,
        theme="t",
        state="open_submission",
        submission_opened_at=OPEN_TIME,
    )
    db_session.add(round_)
    await db_session.commit()
    round_id, org_id = round_.id, organizer.id

    async with _build_client(session_factory, email_spy) as client:
        resp = await client.patch(
            f"/api/v1/rounds/{round_id}", json={"state": "open_voting"}, headers=_auth(org_id)
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "open_voting"
    assert (await _round(db_session, round_id)).state == "open_voting"


async def test_create_stamps_submission_opened_at(session_factory, db_session, email_spy):
    # Scenario 12a: creating a round (born open_submission) stamps
    # submission_opened_at.
    organizer = await _seed_user(db_session, "org@example.com")
    league = League(name="L", organizer_id=organizer.id, total_rounds=2, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id, joined_at=BEFORE))
    await db_session.commit()
    league_id, org_id = league.id, organizer.id

    async with _build_client(session_factory, email_spy) as client:
        resp = await client.post(
            f"/api/v1/leagues/{league_id}/rounds", json={"theme": "x"}, headers=_auth(org_id)
        )
    assert resp.status_code == 201, resp.text
    round_id = uuid.UUID(resp.json()["id"])
    assert (await _round(db_session, round_id)).submission_opened_at is not None


async def test_advance_stamps_submission_opened_at(session_factory, db_session, email_spy):
    # Scenario 12b: advancing a pending round to open_submission stamps
    # submission_opened_at (and sets it as the league's current round).
    organizer = await _seed_user(db_session, "org@example.com")
    league = League(name="L", organizer_id=organizer.id, total_rounds=2, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id, joined_at=BEFORE))
    round_ = Round(league_id=league.id, round_number=1, theme="t", state="pending")
    db_session.add(round_)
    await db_session.commit()
    round_id, league_id, org_id = round_.id, league.id, organizer.id
    # A pending round has not opened yet.
    assert (await _round(db_session, round_id)).submission_opened_at is None

    async with _build_client(session_factory, email_spy) as client:
        resp = await client.patch(
            f"/api/v1/rounds/{round_id}",
            json={"state": "open_submission"},
            headers=_auth(org_id),
        )
    assert resp.status_code == 200, resp.text
    assert (await _round(db_session, round_id)).submission_opened_at is not None
    assert (await _league(db_session, league_id)).current_round == 1


async def test_migration_backfill_stamps_non_pending_rounds(db_session):
    # Scenario 12c: the migration's backfill SQL stamps submission_opened_at =
    # now() for non-pending rounds (NOT created_at — created_at is league-creation
    # time, which predates when members joined and would leave an open round with an
    # empty active-at-open set), and leaves pending rounds NULL.
    organizer = await _seed_user(db_session, "org@example.com")
    league = League(name="L", organizer_id=organizer.id, total_rounds=2, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    # An in-flight (non-pending) round with a NULL stamp, as if it predated the
    # column, plus a pending round that should stay NULL.
    open_round = Round(
        league_id=league.id,
        round_number=1,
        theme="t",
        state="open_voting",
        submission_opened_at=None,
    )
    pending_round = Round(
        league_id=league.id, round_number=2, theme="t2", state="pending", submission_opened_at=None
    )
    db_session.add(open_round)
    db_session.add(pending_round)
    await db_session.commit()
    open_id, pending_id = open_round.id, pending_round.id

    # The migration's backfill statement (verbatim from the upgrade()).
    await db_session.execute(
        text("UPDATE rounds SET submission_opened_at = now() WHERE state != 'pending'")
    )
    await db_session.commit()

    # Capture attributes into locals as each row is loaded: the next _round call's
    # expire_all() would expire a held object and a later attribute read would
    # lazy-load in a sync context (MissingGreenlet).
    backfilled = await _round(db_session, open_id)
    bf_opened, bf_created = backfilled.submission_opened_at, backfilled.created_at
    pending_opened = (await _round(db_session, pending_id)).submission_opened_at
    # Non-pending round gets a non-null stamp at/after its creation (now()).
    assert bf_opened is not None
    assert bf_opened >= bf_created
    assert pending_opened is None
