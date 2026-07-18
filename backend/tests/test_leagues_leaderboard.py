"""Tests for GET /api/v1/clubs/{league_id}/leaderboard (MYS-157).

Covers: auth (401), not-found (404), non-member (403), happy-path ranking,
tie-breaking, 0-vote members, exclusion of open-round votes, and exclusion of
removed members.
"""

import uuid
from datetime import datetime, timezone

from app.auth.jwt import create_access_token
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, name: str) -> User:
    user = User(email=email, display_name=name)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_league(db_session, organizer: User) -> League:
    league = League(
        name="Test League", organizer_id=organizer.id, total_rounds=6, votes_per_player=3
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(league)
    return league


async def _add_member(db_session, league: League, user: User, *, removed: bool = False) -> None:
    m = LeagueMember(
        league_id=league.id,
        user_id=user.id,
        removed_at=datetime.now(timezone.utc) if removed else None,
    )
    db_session.add(m)
    await db_session.commit()


async def _seed_round(db_session, league: League, *, state: str = "closed") -> Round:
    r = Round(league_id=league.id, round_number=1, theme="theme", state=state)
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)
    return r


async def _seed_submission(db_session, round_: Round, user: User) -> Submission:
    sub = Submission(
        round_id=round_.id,
        user_id=user.id,
        isrc="USABC1234567",
        title="Song",
        artist="Artist",
        album="Album",
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _seed_vote(db_session, round_: Round, voter: User, submission: Submission) -> None:
    db_session.add(Vote(round_id=round_.id, voter_id=voter.id, submission_id=submission.id))
    await db_session.commit()


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _url(league_id) -> str:
    return f"/api/v1/clubs/{league_id}/leaderboard"


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


async def test_unauthenticated_returns_401(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    league = await _seed_league(db_session, organizer)

    resp = await client.get(_url(league.id))

    assert resp.status_code == 401


async def test_unknown_league_returns_404(client, db_session):
    user = await _seed_user(db_session, "u@x.com", "User")

    resp = await client.get(_url(uuid.uuid4()), headers=_auth(user.id))

    assert resp.status_code == 404


async def test_non_member_returns_403(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    league = await _seed_league(db_session, organizer)
    stranger = await _seed_user(db_session, "stranger@x.com", "Stranger")

    resp = await client.get(_url(league.id), headers=_auth(stranger.id))

    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #


async def test_response_has_required_keys(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    league = await _seed_league(db_session, organizer)

    resp = await client.get(_url(league.id), headers=_auth(organizer.id))

    assert resp.status_code == 200
    entry = resp.json()[0]
    assert set(entry.keys()) == {"user_id", "display_name", "vote_count", "rank"}


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


async def test_members_ranked_by_votes_descending(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    alice = await _seed_user(db_session, "alice@x.com", "Alice")
    bob = await _seed_user(db_session, "bob@x.com", "Bob")
    league = await _seed_league(db_session, organizer)
    await _add_member(db_session, league, alice)
    await _add_member(db_session, league, bob)

    round_ = await _seed_round(db_session, league, state="closed")
    alice_sub = await _seed_submission(db_session, round_, alice)
    bob_sub = await _seed_submission(db_session, round_, bob)

    # Alice gets 2 votes, Bob gets 1.
    await _seed_vote(db_session, round_, organizer, alice_sub)
    await _seed_vote(db_session, round_, bob, alice_sub)
    await _seed_vote(db_session, round_, alice, bob_sub)

    resp = await client.get(_url(league.id), headers=_auth(organizer.id))
    data = resp.json()

    assert resp.status_code == 200
    by_name = {e["display_name"]: e for e in data}
    assert by_name["Alice"]["vote_count"] == 2
    assert by_name["Alice"]["rank"] == 1
    assert by_name["Bob"]["vote_count"] == 1
    assert by_name["Bob"]["rank"] == 2
    # Alice is first in the list
    assert data[0]["display_name"] == "Alice"


async def test_zero_vote_members_included(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    alice = await _seed_user(db_session, "alice@x.com", "Alice")
    league = await _seed_league(db_session, organizer)
    await _add_member(db_session, league, alice)

    # No rounds, no votes — alice and organizer both show 0
    resp = await client.get(_url(league.id), headers=_auth(organizer.id))
    data = resp.json()

    assert resp.status_code == 200
    assert len(data) == 2
    assert all(e["vote_count"] == 0 for e in data)


async def test_open_round_votes_excluded(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    alice = await _seed_user(db_session, "alice@x.com", "Alice")
    league = await _seed_league(db_session, organizer)
    await _add_member(db_session, league, alice)

    open_round = await _seed_round(db_session, league, state="open_voting")
    alice_sub = await _seed_submission(db_session, open_round, alice)
    await _seed_vote(db_session, open_round, organizer, alice_sub)

    resp = await client.get(_url(league.id), headers=_auth(organizer.id))
    data = resp.json()

    assert resp.status_code == 200
    # Votes from open_voting round must not count.
    assert all(e["vote_count"] == 0 for e in data)


async def test_ties_broken_alphabetically(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Zara")
    alice = await _seed_user(db_session, "alice@x.com", "Alice")
    bob = await _seed_user(db_session, "bob@x.com", "Bob")
    league = await _seed_league(db_session, organizer)
    await _add_member(db_session, league, alice)
    await _add_member(db_session, league, bob)

    round_ = await _seed_round(db_session, league, state="closed")
    alice_sub = await _seed_submission(db_session, round_, alice)
    bob_sub = await _seed_submission(db_session, round_, bob)
    await _seed_vote(db_session, round_, organizer, alice_sub)
    await _seed_vote(db_session, round_, organizer, bob_sub)

    resp = await client.get(_url(league.id), headers=_auth(organizer.id))
    data = resp.json()

    assert resp.status_code == 200
    # Alice and Bob both have 1 vote — same rank, Alice sorts first.
    names = [e["display_name"] for e in data if e["vote_count"] == 1]
    assert names == ["Alice", "Bob"]
    ranks = {e["display_name"]: e["rank"] for e in data}
    assert ranks["Alice"] == ranks["Bob"]


async def test_removed_members_excluded(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    gone = await _seed_user(db_session, "gone@x.com", "Gone")
    league = await _seed_league(db_session, organizer)
    await _add_member(db_session, league, gone, removed=True)

    resp = await client.get(_url(league.id), headers=_auth(organizer.id))
    data = resp.json()

    assert resp.status_code == 200
    names = [e["display_name"] for e in data]
    assert "Gone" not in names


async def test_votes_aggregate_across_multiple_closed_rounds(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    alice = await _seed_user(db_session, "alice@x.com", "Alice")
    league = await _seed_league(db_session, organizer)
    await _add_member(db_session, league, alice)

    r1 = await _seed_round(db_session, league, state="closed")
    r2 = Round(league_id=league.id, round_number=2, theme="r2", state="closed")
    db_session.add(r2)
    await db_session.commit()
    await db_session.refresh(r2)

    sub1 = await _seed_submission(db_session, r1, alice)
    sub2 = await _seed_submission(db_session, r2, alice)
    await _seed_vote(db_session, r1, organizer, sub1)
    await _seed_vote(db_session, r2, organizer, sub2)

    resp = await client.get(_url(league.id), headers=_auth(organizer.id))
    data = resp.json()

    assert resp.status_code == 200
    alice_entry = next(e for e in data if e["display_name"] == "Alice")
    assert alice_entry["vote_count"] == 2
