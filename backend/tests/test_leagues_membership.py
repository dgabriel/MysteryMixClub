"""Tests for MYS-60 / MYS-112: per-league participation (vibe) mode.

Covers leagues.default_vibe_mode (the admin default, seeded onto the organizer
at creation), the GET/PATCH /leagues/:id/membership endpoints for a member's own
per-league vibe setting, and the auth/membership gates.
"""

import uuid

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.user import User


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _seed_user(db_session, email: str) -> User:
    user = User(email=email, display_name="U")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_league(db_session, organizer: User, *, default_vibe_mode: bool = False) -> League:
    league = League(
        name="L",
        organizer_id=organizer.id,
        total_rounds=3,
        votes_per_player=3,
        default_vibe_mode=default_vibe_mode,
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(
        LeagueMember(league_id=league.id, user_id=organizer.id, vibe_mode=default_vibe_mode)
    )
    await db_session.commit()
    await db_session.refresh(league)
    return league


async def _membership(db_session, league_id, user_id) -> LeagueMember:
    return await db_session.scalar(
        select(LeagueMember).where(
            LeagueMember.league_id == league_id, LeagueMember.user_id == user_id
        )
    )


# --------------------------------------------------------------------------- #
# Create — league default seeds the organizer's membership
# --------------------------------------------------------------------------- #


async def test_create_with_default_vibe_seeds_league_and_organizer(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    resp = await client.post(
        "/api/v1/leagues",
        json={"name": "Vibes", "total_rounds": 3, "default_vibe_mode": True},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["default_vibe_mode"] is True

    league_id = uuid.UUID(resp.json()["id"])
    membership = await _membership(db_session, league_id, organizer.id)
    assert membership.vibe_mode is True


async def test_create_defaults_to_playing(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    resp = await client.post(
        "/api/v1/leagues",
        json={"name": "L", "total_rounds": 3},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["default_vibe_mode"] is False
    membership = await _membership(db_session, uuid.UUID(resp.json()["id"]), organizer.id)
    assert membership.vibe_mode is False


# --------------------------------------------------------------------------- #
# GET / PATCH /leagues/:id/membership — the caller's own setting
# --------------------------------------------------------------------------- #


async def test_get_membership_returns_caller_setting(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    league = await _seed_league(db_session, organizer, default_vibe_mode=True)
    resp = await client.get(f"/api/v1/leagues/{league.id}/membership", headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["vibe_mode"] is True
    assert body["user_id"] == str(organizer.id)
    assert body["league_id"] == str(league.id)


async def test_patch_membership_updates_caller_setting(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    league = await _seed_league(db_session, organizer, default_vibe_mode=False)
    # Capture PKs before expire_all so the re-read below doesn't lazy-load.
    league_id, organizer_id = league.id, organizer.id

    resp = await client.patch(
        f"/api/v1/leagues/{league_id}/membership",
        json={"vibe_mode": True},
        headers=_auth(organizer_id),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["vibe_mode"] is True

    db_session.expire_all()
    membership = await _membership(db_session, league_id, organizer_id)
    assert membership.vibe_mode is True


async def test_patch_membership_can_toggle_back_off(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    league = await _seed_league(db_session, organizer, default_vibe_mode=True)

    resp = await client.patch(
        f"/api/v1/leagues/{league.id}/membership",
        json={"vibe_mode": False},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["vibe_mode"] is False


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #


async def test_membership_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    league = await _seed_league(db_session, organizer)
    assert (await client.get(f"/api/v1/leagues/{league.id}/membership")).status_code == 401


async def test_membership_non_member_forbidden(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    outsider = await _seed_user(db_session, "x@example.com")
    league = await _seed_league(db_session, organizer)

    get_resp = await client.get(
        f"/api/v1/leagues/{league.id}/membership", headers=_auth(outsider.id)
    )
    assert get_resp.status_code == 403
    patch_resp = await client.patch(
        f"/api/v1/leagues/{league.id}/membership",
        json={"vibe_mode": True},
        headers=_auth(outsider.id),
    )
    assert patch_resp.status_code == 403
