"""Tests for MYS-34: GET /api/v1/clubs (list clubs for current user).

TDD-first: written before the endpoint exists on the clubs router, so they
are expected to FAIL (red) until the developer implements the route. See
technical-design.md §6 (clubs, club_members) and §7 (Clubs API:
GET /clubs — get all clubs for current user).

Covers auth (401), the empty case, the active-membership filter (organizer and
non-organizer members included; removed members and never-joined clubs
excluded), the full club object shape, and created_at-descending ordering.
"""

import uuid
from datetime import datetime, timedelta, timezone

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.user import User

CLUBS_URL = "/api/v1/clubs"

# The full club object key set, matching POST /clubs.
_CLUB_KEYS = {
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


async def _seed_club(db_session, organizer: User, **overrides) -> Club:
    """Insert and commit a Club with the organizer as an active member.

    Accepts column overrides (e.g. created_at) passed straight to the Club
    constructor.
    """
    defaults = {
        "name": "Summer Bangers",
        "description": "A club for hot tracks",
        "organizer_id": organizer.id,
        "total_mixes": 6,
        "votes_per_player": 5,
        "current_mix": 0,
        "state": "active",
    }
    defaults.update(overrides)
    club = Club(**defaults)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(club)
    return club


async def _seed_member(db_session, club: Club, user: User, **overrides) -> ClubMember:
    """Insert and commit a ClubMember row, returning it.

    Accepts column overrides (e.g. joined_at, removed_at).
    """
    defaults = {"club_id": club.id, "user_id": user.id}
    defaults.update(overrides)
    member = ClubMember(**defaults)
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


# ========================================================================== #
# Auth
# ========================================================================== #


async def test_unauthenticated_list_returns_401(client):
    resp = await client.get(CLUBS_URL)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


# ========================================================================== #
# Empty case
# ========================================================================== #


async def test_no_memberships_returns_200_and_empty_array(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.get(CLUBS_URL, headers=_auth_header(user.id))

    assert resp.status_code == 200, resp.text
    assert resp.json() == []


# ========================================================================== #
# Membership filter + full shape
# ========================================================================== #


async def test_returns_organized_and_member_clubs_with_full_shape(client, db_session):
    caller = await _seed_user(db_session, email="caller@example.com", display_name="Caller")
    other = await _seed_user(db_session, email="other@example.com", display_name="Other")

    # Club the caller organizes (organizer is an active member).
    organized = await _seed_club(db_session, caller, name="Organized")
    # Club owned by someone else, where the caller is an active member.
    joined = await _seed_club(db_session, other, name="Joined")
    await _seed_member(db_session, joined, caller)

    resp = await client.get(CLUBS_URL, headers=_auth_header(caller.id))

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    returned_ids = {item["id"] for item in data}
    assert returned_ids == {str(organized.id), str(joined.id)}
    for item in data:
        assert set(item.keys()) == _CLUB_KEYS


async def test_excludes_removed_and_never_joined_clubs(client, db_session):
    caller = await _seed_user(db_session, email="caller@example.com", display_name="Caller")
    other = await _seed_user(db_session, email="other@example.com", display_name="Other")

    # Club the caller is an active member of — should appear.
    member_club = await _seed_club(db_session, other, name="MemberClub")
    await _seed_member(db_session, member_club, caller)

    # Club the caller was removed from — should NOT appear.
    removed_club = await _seed_club(db_session, other, name="RemovedClub")
    await _seed_member(db_session, removed_club, caller, removed_at=datetime.now(timezone.utc))

    # Club the caller never joined — should NOT appear.
    stranger_club = await _seed_club(db_session, other, name="StrangerClub")

    resp = await client.get(CLUBS_URL, headers=_auth_header(caller.id))

    assert resp.status_code == 200, resp.text
    returned_ids = {item["id"] for item in resp.json()}
    assert returned_ids == {str(member_club.id)}
    assert str(removed_club.id) not in returned_ids
    assert str(stranger_club.id) not in returned_ids


# ========================================================================== #
# Ordering — created_at descending
# ========================================================================== #


async def test_results_ordered_created_at_descending(client, db_session):
    caller = await _seed_user(db_session, email="caller@example.com", display_name="Caller")

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    oldest = await _seed_club(db_session, caller, name="Oldest", created_at=base)
    middle = await _seed_club(
        db_session, caller, name="Middle", created_at=base + timedelta(days=1)
    )
    newest = await _seed_club(
        db_session, caller, name="Newest", created_at=base + timedelta(days=2)
    )

    resp = await client.get(CLUBS_URL, headers=_auth_header(caller.id))

    assert resp.status_code == 200, resp.text
    returned_ids = [item["id"] for item in resp.json()]
    assert returned_ids == [str(newest.id), str(middle.id), str(oldest.id)]
