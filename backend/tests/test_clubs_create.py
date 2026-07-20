"""Tests for MYS-12: POST /api/v1/clubs (create league).

TDD-first: these are written before the endpoint and the Club /
ClubMember models exist, so they are expected to FAIL (red) until the
developer implements them.

Covers auth (401), happy-path response shape, persistence of the leagues row
and the organizer's league_members row, the votes_per_player default, the
optional description, request-validation 422s, and name trimming. See
technical-design.md §6 (leagues, league_members) and §7 (Leagues API).
"""

import uuid

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.user import User

LEAGUES_URL = "/api/v1/clubs"

# The exact key set the create response must return.
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


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _valid_body(**overrides) -> dict:
    body = {
        "name": "Summer Bangers",
        "description": "A league for hot tracks",
        "total_mixes": 6,
        "votes_per_player": 5,
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


async def test_unauthenticated_create_returns_401(client):
    resp = await client.post(LEAGUES_URL, json=_valid_body())

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


# --------------------------------------------------------------------------- #
# Happy path — response shape
# --------------------------------------------------------------------------- #


async def test_create_returns_201_and_full_league_shape(client, db_session):
    user = await _seed_user(db_session)
    body = _valid_body(
        name="Summer Bangers",
        description="A league for hot tracks",
        total_mixes=6,
        votes_per_player=5,
    )

    resp = await client.post(LEAGUES_URL, headers=_auth_header(user.id), json=body)

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert set(data.keys()) == _LEAGUE_KEYS
    # Echoes input.
    assert data["name"] == "Summer Bangers"
    assert data["description"] == "A league for hot tracks"
    assert data["total_mixes"] == 6
    assert data["votes_per_player"] == 5
    # Server-set fields.
    assert data["organizer_id"] == str(user.id)
    assert data["current_mix"] == 0
    assert data["state"] == "active"
    assert data["completed_at"] is None
    # id is a valid UUID string.
    assert uuid.UUID(data["id"])


# --------------------------------------------------------------------------- #
# Persistence side effects
# --------------------------------------------------------------------------- #


async def test_create_persists_league_and_organizer_membership(client, db_session):
    user = await _seed_user(db_session)
    user_id = user.id

    resp = await client.post(LEAGUES_URL, headers=_auth_header(user_id), json=_valid_body())

    assert resp.status_code == 201, resp.text

    db_session.expire_all()

    leagues = (await db_session.scalars(select(Club))).all()
    assert len(leagues) == 1
    league = leagues[0]
    assert league.organizer_id == user_id
    assert league.current_mix == 0
    assert league.state == "active"
    assert league.completed_at is None

    members = (
        await db_session.scalars(
            select(ClubMember).where(
                ClubMember.club_id == league.id,
                ClubMember.user_id == user_id,
            )
        )
    ).all()
    assert len(members) == 1
    assert members[0].removed_at is None


# --------------------------------------------------------------------------- #
# Defaults / optional fields
# --------------------------------------------------------------------------- #


async def test_votes_per_player_defaults_to_3_when_omitted(client, db_session):
    user = await _seed_user(db_session)
    body = _valid_body()
    body.pop("votes_per_player")

    resp = await client.post(LEAGUES_URL, headers=_auth_header(user.id), json=body)

    assert resp.status_code == 201, resp.text
    assert resp.json()["votes_per_player"] == 3


async def test_songs_per_submission_defaults_to_1_when_omitted(client, db_session):
    user = await _seed_user(db_session)
    body = _valid_body()
    body.pop("songs_per_submission", None)

    resp = await client.post(LEAGUES_URL, headers=_auth_header(user.id), json=body)

    assert resp.status_code == 201, resp.text
    assert resp.json()["songs_per_submission"] == 1


async def test_songs_per_submission_accepts_up_to_5(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.post(
        LEAGUES_URL, headers=_auth_header(user.id), json=_valid_body(songs_per_submission=5)
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["songs_per_submission"] == 5


async def test_songs_per_submission_below_1_returns_422(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.post(
        LEAGUES_URL, headers=_auth_header(user.id), json=_valid_body(songs_per_submission=0)
    )

    assert resp.status_code == 422, resp.text


async def test_songs_per_submission_above_5_returns_422(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.post(
        LEAGUES_URL, headers=_auth_header(user.id), json=_valid_body(songs_per_submission=6)
    )

    assert resp.status_code == 422, resp.text


async def test_description_optional_defaults_to_null(client, db_session):
    user = await _seed_user(db_session)
    body = _valid_body()
    body.pop("description")

    resp = await client.post(LEAGUES_URL, headers=_auth_header(user.id), json=body)

    assert resp.status_code == 201, resp.text
    assert resp.json()["description"] is None


# --------------------------------------------------------------------------- #
# Validation rejections (422)
# --------------------------------------------------------------------------- #


async def test_missing_name_returns_422(client, db_session):
    user = await _seed_user(db_session)
    body = _valid_body()
    body.pop("name")

    resp = await client.post(LEAGUES_URL, headers=_auth_header(user.id), json=body)

    assert resp.status_code == 422, resp.text


async def test_empty_name_returns_422(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.post(LEAGUES_URL, headers=_auth_header(user.id), json=_valid_body(name=""))

    assert resp.status_code == 422, resp.text


async def test_whitespace_only_name_returns_422(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.post(
        LEAGUES_URL, headers=_auth_header(user.id), json=_valid_body(name="   ")
    )

    assert resp.status_code == 422, resp.text


async def test_name_too_long_returns_422(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.post(
        LEAGUES_URL, headers=_auth_header(user.id), json=_valid_body(name="x" * 101)
    )

    assert resp.status_code == 422, resp.text


async def test_missing_total_rounds_defaults_to_6(client, db_session):
    # total_rounds now defaults to 6 (MYS-62): omitting it is valid and yields a
    # 201 with six auto-generated pending rounds.
    user = await _seed_user(db_session)
    body = _valid_body()
    body.pop("total_mixes")

    resp = await client.post(LEAGUES_URL, headers=_auth_header(user.id), json=body)

    assert resp.status_code == 201, resp.text
    assert resp.json()["total_mixes"] == 6


async def test_total_rounds_below_one_returns_422(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.post(
        LEAGUES_URL, headers=_auth_header(user.id), json=_valid_body(**{"total_mixes": 0})
    )

    assert resp.status_code == 422, resp.text


async def test_votes_per_player_below_one_returns_422(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.post(
        LEAGUES_URL,
        headers=_auth_header(user.id),
        json=_valid_body(votes_per_player=0),
    )

    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- #
# Name trimming
# --------------------------------------------------------------------------- #


async def test_name_is_trimmed(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.post(
        LEAGUES_URL,
        headers=_auth_header(user.id),
        json=_valid_body(name="  My Club  "),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "My Club"
