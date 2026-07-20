"""Tests for MYS-124: DELETE /api/v1/clubs/{league_id} (organizer-only, cascade).

A league can be hard-deleted by its organizer in ANY state (MYS-137) — not
started, in progress (a round open), or complete. The delete cascades, in FK
dependency order, to votes, notes, submissions, rounds, invites, and
league_members — leaving no orphan rows. The users themselves are NOT deleted.

Covers: 401 unauthenticated, 403 non-organizer, 404 missing league, and 204 +
no-orphans for a not-started league, an in-flight league (open round with
submission/vote), and a complete league with real round data.

PKs are captured into locals before any expire_all (project MissingGreenlet
gotcha). See technical-design.md §6 and the MYS-124 plan.
"""

import uuid

from sqlalchemy import func, select

from app.auth.jwt import create_access_token
from app.models.invite import Invite
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.note import Note
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, **overrides) -> User:
    defaults = {
        "email": "alice@example.com",
        "display_name": "Alice",
        "preferred_service": None,
    }
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_league(db_session, organizer: User, **overrides) -> League:
    defaults = {
        "name": "Summer Bangers",
        "description": "A league for hot tracks",
        "organizer_id": organizer.id,
        "total_mixes": 6,
        "votes_per_player": 5,
        "current_mix": 0,
        "state": "active",
    }
    defaults.update(overrides)
    league = League(**defaults)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(league)
    return league


async def _seed_member(db_session, league: League, user: User, **overrides) -> LeagueMember:
    defaults = {"club_id": league.id, "user_id": user.id}
    defaults.update(overrides)
    member = LeagueMember(**defaults)
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _delete_url(league_id) -> str:
    return f"/api/v1/clubs/{league_id}"


async def _count(db_session, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for attr, value in filters.items():
        stmt = stmt.where(getattr(model, attr) == value)
    return await db_session.scalar(stmt)


# ========================================================================== #
# Auth / not found
# ========================================================================== #


async def test_delete_unauthenticated_returns_401(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)

    resp = await client.delete(_delete_url(league.id))

    assert resp.status_code == 401, resp.text


async def test_delete_missing_league_returns_404(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.delete(_delete_url(uuid.uuid4()), headers=_auth_header(user.id))

    assert resp.status_code == 404, resp.text


async def test_delete_non_organizer_member_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)

    resp = await client.delete(_delete_url(league.id), headers=_auth_header(member.id))

    assert resp.status_code == 403, resp.text

    # The league still exists.
    league_id = league.id
    db_session.expire_all()
    assert await db_session.scalar(select(League).where(League.id == league_id)) is not None


async def test_delete_outsider_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    outsider = await _seed_user(db_session, email="out@example.com", display_name="Out")

    resp = await client.delete(_delete_url(league.id), headers=_auth_header(outsider.id))

    assert resp.status_code == 403, resp.text


# ========================================================================== #
# In-flight league — now deletable in any state (MYS-137)
# ========================================================================== #


async def test_delete_in_flight_league_is_allowed_and_cascades(client, db_session):
    # MYS-137: an in-progress league (state == active AND current_round > 0, with
    # an open round + submission + vote) can be deleted, and everything cascades.
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer, state="active", current_round=1)
    player = await _seed_user(db_session, email="player@example.com", display_name="Player")
    await _seed_member(db_session, league, player)

    round_ = Round(league_id=league.id, round_number=1, state="open_voting")
    db_session.add(round_)
    await db_session.flush()
    submission = Submission(
        round_id=round_.id,
        user_id=player.id,
        isrc="USEXAMPLE0009",
        title="Mid-round Song",
        artist="An Artist",
    )
    db_session.add(submission)
    await db_session.flush()
    db_session.add(Vote(round_id=round_.id, voter_id=organizer.id, submission_id=submission.id))
    await db_session.commit()

    league_id = league.id
    round_id = round_.id

    resp = await client.delete(_delete_url(league.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert await db_session.scalar(select(League).where(League.id == league_id)) is None
    assert await _count(db_session, Round, league_id=league_id) == 0
    assert await _count(db_session, Submission, round_id=round_id) == 0
    assert await _count(db_session, Vote, round_id=round_id) == 0


async def test_delete_active_but_not_started_league_is_allowed(client, db_session):
    # state == active but current_round == 0 -> not yet started, delete is fine.
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer, state="active", current_round=0)

    resp = await client.delete(_delete_url(league.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 204, resp.text


# ========================================================================== #
# Happy path — not-started league, 204 + no orphans
# ========================================================================== #


async def test_delete_not_started_league_cascades_rounds_invites_members(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer, current_round=0)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)
    # A pending round slate (as auto-generated at creation) + an email invite.
    db_session.add(Round(league_id=league.id, round_number=1, state="pending"))
    db_session.add(Round(league_id=league.id, round_number=2, state="pending"))
    db_session.add(
        Invite(
            league_id=league.id,
            created_by=organizer.id,
            token="tok_" + uuid.uuid4().hex,
        )
    )
    await db_session.commit()

    league_id = league.id
    organizer_id = organizer.id
    member_id = member.id

    resp = await client.delete(_delete_url(league.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 204, resp.text
    assert resp.content == b""

    db_session.expire_all()
    assert await db_session.scalar(select(League).where(League.id == league_id)) is None
    assert await _count(db_session, Round, league_id=league_id) == 0
    assert await _count(db_session, Invite, league_id=league_id) == 0
    assert await _count(db_session, LeagueMember, league_id=league_id) == 0
    # The user accounts survive the league deletion.
    assert await db_session.scalar(select(User).where(User.id == organizer_id)) is not None
    assert await db_session.scalar(select(User).where(User.id == member_id)) is not None


# ========================================================================== #
# Happy path — complete league with real data, 204 + no orphans
# ========================================================================== #


async def test_delete_complete_league_cascades_submissions_votes_notes(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer, state="complete", current_round=1)
    player = await _seed_user(db_session, email="player@example.com", display_name="Player")
    await _seed_member(db_session, league, player)

    # A closed round with a submission, a vote, and a note.
    round_ = Round(league_id=league.id, round_number=1, state="closed")
    db_session.add(round_)
    await db_session.flush()
    submission = Submission(
        round_id=round_.id,
        user_id=player.id,
        isrc="USEXAMPLE0001",
        title="A Song",
        artist="An Artist",
    )
    db_session.add(submission)
    await db_session.flush()
    db_session.add(Vote(round_id=round_.id, voter_id=organizer.id, submission_id=submission.id))
    db_session.add(
        Note(
            round_id=round_.id,
            author_id=organizer.id,
            submission_id=submission.id,
            body="great pick",
        )
    )
    db_session.add(
        Invite(
            league_id=league.id,
            created_by=organizer.id,
            token="tok_" + uuid.uuid4().hex,
        )
    )
    await db_session.commit()

    league_id = league.id
    round_id = round_.id
    organizer_id = organizer.id
    player_id = player.id

    resp = await client.delete(_delete_url(league.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    # Nothing tied to this league or its round survives.
    assert await db_session.scalar(select(League).where(League.id == league_id)) is None
    assert await _count(db_session, Round, league_id=league_id) == 0
    assert await _count(db_session, Submission, round_id=round_id) == 0
    assert await _count(db_session, Vote, round_id=round_id) == 0
    assert await _count(db_session, Note, round_id=round_id) == 0
    assert await _count(db_session, Invite, league_id=league_id) == 0
    assert await _count(db_session, LeagueMember, league_id=league_id) == 0
    # Users are untouched.
    assert await db_session.scalar(select(User).where(User.id == organizer_id)) is not None
    assert await db_session.scalar(select(User).where(User.id == player_id)) is not None


async def test_delete_only_targets_its_own_league(client, db_session):
    # A second league's data must be left fully intact.
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    doomed = await _seed_league(db_session, organizer, name="Doomed", current_round=0)
    keeper = await _seed_league(db_session, organizer, name="Keeper", current_round=0)
    db_session.add(Round(league_id=keeper.id, round_number=1, state="pending"))
    db_session.add(
        Invite(
            league_id=keeper.id,
            created_by=organizer.id,
            token="tok_" + uuid.uuid4().hex,
        )
    )
    await db_session.commit()

    keeper_id = keeper.id

    resp = await client.delete(_delete_url(doomed.id), headers=_auth_header(organizer.id))
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert await db_session.scalar(select(League).where(League.id == keeper_id)) is not None
    assert await _count(db_session, Round, league_id=keeper_id) == 1
    assert await _count(db_session, Invite, league_id=keeper_id) == 1
    # Keeper's organizer membership row still present.
    assert await _count(db_session, LeagueMember, league_id=keeper_id) == 1
