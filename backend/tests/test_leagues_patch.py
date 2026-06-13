"""Tests for MYS-14: PATCH /api/v1/leagues/{league_id} (update league).

TDD-first: written before the endpoint exists, so they are expected to FAIL
(red) until the developer implements the route on the existing leagues router.

Covers auth (401), not-found (404), organizer-only authorization (403 for both
non-organizer members and non-member strangers), state/rounds conflicts (409),
the partial-update happy path with persistence, and request-validation 422s.
See technical-design.md §6 (leagues, league_members) and §7 (Leagues API:
PATCH /leagues/:id — organizer only).
"""

import uuid

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.user import User

# The full league object key set, matching POST /leagues.
_LEAGUE_KEYS = {
    "id",
    "name",
    "description",
    "organizer_id",
    "total_rounds",
    "votes_per_player",
    "current_round",
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
        "default_vibe_mode": False,
    }
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_league(db_session, organizer: User, **overrides) -> League:
    """Insert and commit a League with the organizer as an active member."""
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
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(league)
    return league


async def _seed_member(db_session, league: League, user: User, **overrides) -> LeagueMember:
    """Insert and commit a LeagueMember row, returning it."""
    defaults = {"league_id": league.id, "user_id": user.id}
    defaults.update(overrides)
    member = LeagueMember(**defaults)
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _patch_url(league_id) -> str:
    return f"/api/v1/leagues/{league_id}"


# ========================================================================== #
# Auth
# ========================================================================== #


async def test_unauthenticated_patch_returns_401(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)

    resp = await client.patch(_patch_url(league.id), json={"name": "New Name"})

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


# ========================================================================== #
# Not found
# ========================================================================== #


async def test_patch_unknown_league_returns_404(client, db_session):
    organizer = await _seed_user(db_session)

    resp = await client.patch(
        _patch_url(uuid.uuid4()),
        headers=_auth_header(organizer.id),
        json={"name": "New Name"},
    )

    assert resp.status_code == 404, resp.text


# ========================================================================== #
# Authorization (organizer only)
# ========================================================================== #


async def test_non_organizer_member_patch_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)  # active, non-organizer

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(member.id),
        json={"name": "New Name"},
    )

    assert resp.status_code == 403, resp.text


async def test_non_member_stranger_patch_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    stranger = await _seed_user(db_session, email="stranger@example.com", display_name="Stranger")

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(stranger.id),
        json={"name": "New Name"},
    )

    assert resp.status_code == 403, resp.text


# ========================================================================== #
# Happy path — response shape & persistence
# ========================================================================== #


async def test_organizer_updates_all_fields_returns_200_full_shape_and_persists(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(
        db_session, organizer, name="Old Name", description="Old desc", total_rounds=6
    )

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"name": "  Brand New  ", "description": "Fresh desc", "total_rounds": 8},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) == _LEAGUE_KEYS
    assert data["name"] == "Brand New"  # trimmed
    assert data["description"] == "Fresh desc"
    assert data["total_rounds"] == 8

    league_id = league.id
    db_session.expire_all()

    persisted = await db_session.scalar(select(League).where(League.id == league_id))
    assert persisted.name == "Brand New"
    assert persisted.description == "Fresh desc"
    assert persisted.total_rounds == 8


async def test_partial_update_only_name_leaves_other_fields_untouched(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(
        db_session, organizer, name="Old Name", description="Keep me", total_rounds=6
    )

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"name": "Renamed"},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name"] == "Renamed"
    assert data["description"] == "Keep me"
    assert data["total_rounds"] == 6

    league_id = league.id
    db_session.expire_all()

    persisted = await db_session.scalar(select(League).where(League.id == league_id))
    assert persisted.name == "Renamed"
    assert persisted.description == "Keep me"
    assert persisted.total_rounds == 6


async def test_extend_rounds_returns_200(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer, total_rounds=6, current_round=2)

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"total_rounds": 10},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["total_rounds"] == 10


async def test_shorten_to_equal_current_round_returns_200(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer, total_rounds=6, current_round=3)

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"total_rounds": 3},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["total_rounds"] == 3


# ========================================================================== #
# Conflicts (409)
# ========================================================================== #


async def test_shorten_below_current_round_returns_409_and_unchanged(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer, total_rounds=6, current_round=4)

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"total_rounds": 2},
    )

    assert resp.status_code == 409, resp.text

    league_id = league.id
    db_session.expire_all()

    persisted = await db_session.scalar(select(League).where(League.id == league_id))
    assert persisted.total_rounds == 6


async def test_completed_league_edit_returns_409_and_unchanged(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer, name="Old Name", state="complete")

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"name": "New Name"},
    )

    assert resp.status_code == 409, resp.text

    league_id = league.id
    db_session.expire_all()

    persisted = await db_session.scalar(select(League).where(League.id == league_id))
    assert persisted.name == "Old Name"


# ========================================================================== #
# Validation rejections (422)
# ========================================================================== #


async def test_empty_name_returns_422(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"name": ""},
    )

    assert resp.status_code == 422, resp.text


async def test_whitespace_only_name_returns_422(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"name": "   "},
    )

    assert resp.status_code == 422, resp.text


async def test_name_too_long_returns_422(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"name": "x" * 101},
    )

    assert resp.status_code == 422, resp.text


async def test_total_rounds_below_one_returns_422(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"total_rounds": 0},
    )

    assert resp.status_code == 422, resp.text


async def test_explicit_null_name_returns_422(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"name": None},
    )

    assert resp.status_code == 422, resp.text


async def test_explicit_null_total_rounds_returns_422(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"total_rounds": None},
    )

    assert resp.status_code == 422, resp.text


# ========================================================================== #
# description explicit null clears it
# ========================================================================== #


async def test_explicit_null_description_clears_it_returns_200(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer, description="Has a description")

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"description": None},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] is None

    league_id = league.id
    db_session.expire_all()

    persisted = await db_session.scalar(select(League).where(League.id == league_id))
    assert persisted.description is None
