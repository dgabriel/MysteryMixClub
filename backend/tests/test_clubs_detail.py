"""Tests for MYS-34: GET /api/v1/clubs/{league_id} (league detail).

TDD-first: written before the endpoint exists on the leagues router, so they
are expected to FAIL (red) until the developer implements the route. See
technical-design.md §6 (leagues, league_members) and §7 (Leagues API:
GET /leagues/:id — get league detail).

Covers auth (401), not-found (404), the active-member happy path returning the
full league object (organizer and non-organizer member), and 403 for both
non-members and removed members.
"""

import uuid
from datetime import datetime, timezone

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.user import User

# The full league object key set, matching POST /leagues.
_LEAGUE_KEYS = {
    "id",
    "name",
    "description",
    "organizer_id",
    "total_mixes",
    "votes_per_player",
    "songs_per_submission",
    "current_mix",
    "default_vibe_mode",
    "submission_window_hours",
    "voting_window_hours",
    "state",
    "created_at",
    "completed_at",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, **overrides) -> User:
    """Insert and commit a User, returning it. display_name is NOT NULL."""
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


async def _seed_league(db_session, organizer: User, **overrides) -> Club:
    """Insert and commit a Club with the organizer as an active member."""
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
    league = Club(**defaults)
    db_session.add(league)
    await db_session.flush()
    db_session.add(ClubMember(club_id=league.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(league)
    return league


async def _seed_member(db_session, league: Club, user: User, **overrides) -> ClubMember:
    """Insert and commit a ClubMember row, returning it."""
    defaults = {"club_id": league.id, "user_id": user.id}
    defaults.update(overrides)
    member = ClubMember(**defaults)
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _detail_url(league_id) -> str:
    return f"/api/v1/clubs/{league_id}"


# ========================================================================== #
# Auth
# ========================================================================== #


async def test_unauthenticated_detail_returns_401(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)

    resp = await client.get(_detail_url(league.id))

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


# ========================================================================== #
# Not found
# ========================================================================== #


async def test_detail_unknown_league_returns_404(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.get(_detail_url(uuid.uuid4()), headers=_auth_header(user.id))

    assert resp.status_code == 404, resp.text


# ========================================================================== #
# Happy path — active member
# ========================================================================== #


async def test_organizer_detail_returns_200_full_shape(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)
    league_id = str(league.id)

    resp = await client.get(_detail_url(league.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) == _LEAGUE_KEYS
    assert data["id"] == league_id


async def test_non_organizer_member_detail_returns_200_full_shape(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    league_id = str(league.id)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)

    resp = await client.get(_detail_url(league.id), headers=_auth_header(member.id))

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) == _LEAGUE_KEYS
    assert data["id"] == league_id


# ========================================================================== #
# Authorization (403)
# ========================================================================== #


async def test_non_member_stranger_detail_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    stranger = await _seed_user(db_session, email="stranger@example.com", display_name="Stranger")

    resp = await client.get(_detail_url(league.id), headers=_auth_header(stranger.id))

    assert resp.status_code == 403, resp.text


async def test_removed_member_detail_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    removed = await _seed_user(db_session, email="removed@example.com", display_name="Removed")
    await _seed_member(db_session, league, removed, removed_at=datetime.now(timezone.utc))

    resp = await client.get(_detail_url(league.id), headers=_auth_header(removed.id))

    assert resp.status_code == 403, resp.text
