"""Tests for MYS-34: GET /api/v1/leagues/{league_id}/members (member list).

TDD-first: written before the endpoint exists on the leagues router, so they
are expected to FAIL (red) until the developer implements the route. See
technical-design.md §6 (leagues, league_members) and §7 (Leagues API:
GET /leagues/:id/members — get league members).

Covers auth (401), not-found (404), 403 for non-members and removed members,
the active-member happy path returning a privacy-safe member list (no email),
exclusion of removed members, the is_organizer flag, and joined_at-ascending
ordering.
"""

import uuid
from datetime import datetime, timedelta, timezone

from app.auth.jwt import create_access_token
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.user import User

# The exact key set each member item must return. Notably NO "email". is_admin
# was added alongside league co-organizers (MYS-99): true for the fixed
# organizer OR a promoted co-organizer (role == "admin"), broader than
# is_organizer, which only ever means "is the original organizer_id".
_MEMBER_KEYS = {"user_id", "display_name", "joined_at", "is_organizer", "is_admin"}


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


async def _seed_league(db_session, organizer: User, **overrides) -> League:
    """Insert and commit a League with the organizer as an active member.

    The organizer's membership row is created here; pass organizer_joined_at to
    control its joined_at for ordering assertions.
    """
    organizer_joined_at = overrides.pop("organizer_joined_at", None)
    defaults = {
        "name": "Summer Bangers",
        "description": "A league for hot tracks",
        "organizer_id": organizer.id,
        "total_rounds": 6,
        "votes_per_player": 5,
        "current_round": 0,
        "state": "active",
    }
    defaults.update(overrides)
    league = League(**defaults)
    db_session.add(league)
    await db_session.flush()
    member_kwargs = {"league_id": league.id, "user_id": organizer.id}
    if organizer_joined_at is not None:
        member_kwargs["joined_at"] = organizer_joined_at
    db_session.add(LeagueMember(**member_kwargs))
    await db_session.commit()
    await db_session.refresh(league)
    return league


async def _seed_member(db_session, league: League, user: User, **overrides) -> LeagueMember:
    """Insert and commit a LeagueMember row, returning it.

    Accepts column overrides (e.g. joined_at, removed_at).
    """
    defaults = {"league_id": league.id, "user_id": user.id}
    defaults.update(overrides)
    member = LeagueMember(**defaults)
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _members_url(league_id) -> str:
    return f"/api/v1/leagues/{league_id}/members"


# ========================================================================== #
# Auth
# ========================================================================== #


async def test_unauthenticated_members_returns_401(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)

    resp = await client.get(_members_url(league.id))

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


# ========================================================================== #
# Not found
# ========================================================================== #


async def test_members_unknown_league_returns_404(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.get(_members_url(uuid.uuid4()), headers=_auth_header(user.id))

    assert resp.status_code == 404, resp.text


# ========================================================================== #
# Authorization (403)
# ========================================================================== #


async def test_non_member_stranger_members_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    stranger = await _seed_user(db_session, email="stranger@example.com", display_name="Stranger")

    resp = await client.get(_members_url(league.id), headers=_auth_header(stranger.id))

    assert resp.status_code == 403, resp.text


async def test_removed_member_members_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    removed = await _seed_user(db_session, email="removed@example.com", display_name="Removed")
    await _seed_member(db_session, league, removed, removed_at=datetime.now(timezone.utc))

    resp = await client.get(_members_url(league.id), headers=_auth_header(removed.id))

    assert resp.status_code == 403, resp.text


# ========================================================================== #
# Happy path — shape & privacy
# ========================================================================== #


async def test_member_list_returns_200_privacy_safe_shape_no_email(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)

    resp = await client.get(_members_url(league.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2
    for item in data:
        assert set(item.keys()) == _MEMBER_KEYS
        assert "email" not in item


async def test_member_list_excludes_removed_members(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    active = await _seed_user(db_session, email="active@example.com", display_name="Active")
    await _seed_member(db_session, league, active)
    removed = await _seed_user(db_session, email="removed@example.com", display_name="Removed")
    await _seed_member(db_session, league, removed, removed_at=datetime.now(timezone.utc))

    resp = await client.get(_members_url(league.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Organizer + one active member; removed member excluded.
    assert len(data) == 2
    returned_user_ids = {item["user_id"] for item in data}
    assert str(removed.id) not in returned_user_ids
    assert returned_user_ids == {str(organizer.id), str(active.id)}


async def test_is_organizer_flag_true_only_for_organizer(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)

    resp = await client.get(_members_url(league.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    by_user = {item["user_id"]: item for item in resp.json()}
    assert by_user[str(organizer.id)]["is_organizer"] is True
    assert by_user[str(member.id)]["is_organizer"] is False


async def test_is_admin_flag_true_for_organizer_and_promoted_co_organizer_only(client, db_session):
    # MYS-99: is_admin is true for the fixed organizer OR a member promoted to
    # role == "admin"; false for a plain member. Broader than is_organizer,
    # which stays true only for the fixed organizer_id.
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, league, co_organizer, role="admin")
    plain = await _seed_user(db_session, email="plain@example.com", display_name="Plain")
    await _seed_member(db_session, league, plain)

    resp = await client.get(_members_url(league.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    by_user = {item["user_id"]: item for item in resp.json()}
    assert by_user[str(organizer.id)]["is_admin"] is True
    assert by_user[str(co_organizer.id)]["is_admin"] is True
    assert by_user[str(co_organizer.id)]["is_organizer"] is False
    assert by_user[str(plain.id)]["is_admin"] is False


# ========================================================================== #
# Ordering — joined_at ascending (organizer first)
# ========================================================================== #


async def test_member_list_ordered_joined_at_ascending(client, db_session):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer, organizer_joined_at=base)

    first = await _seed_user(db_session, email="first@example.com", display_name="First")
    await _seed_member(db_session, league, first, joined_at=base + timedelta(days=1))
    second = await _seed_user(db_session, email="second@example.com", display_name="Second")
    await _seed_member(db_session, league, second, joined_at=base + timedelta(days=2))

    resp = await client.get(_members_url(league.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    returned_user_ids = [item["user_id"] for item in resp.json()]
    assert returned_user_ids == [str(organizer.id), str(first.id), str(second.id)]
    # Organizer joined at creation, so they are first.
    assert returned_user_ids[0] == str(organizer.id)
