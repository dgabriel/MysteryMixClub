"""Tests for MYS-62: mixes auto-generated at club creation.

When a club is created the backend inserts its full slate of ``pending``
mixes (one per ``total_mixes``, default 6), numbered 1..N with no theme or
description and the club's ``votes_per_player``. ``current_mix`` stays 0
until a mix is opened. theme is now nullable end-to-end, so a pending mix's
theme/description can be set and later cleared while it is still pending.

Reuses the seed/auth helpers in ``test_mixes.py`` for users and membership, but
creates clubs through the POST endpoint so the auto-generation runs.
"""

import uuid

from sqlalchemy import select

from app.models.club import Club
from app.models.mix import Mix

from tests.test_mixes import (  # reuse established helpers
    _add_member,
    _advance,
    _auth,
    _mixes_url,
    _seed_user,
)

CLUBS_URL = "/api/v1/clubs"


async def _create_club(client, user_id, *, name="Autogen Club", **fields):
    body = {"name": name}
    body.update(fields)
    return await client.post(CLUBS_URL, json=body, headers=_auth(user_id))


async def _mixes_for(db_session, club_id):
    return list(
        await db_session.scalars(
            select(Mix).where(Mix.club_id == club_id).order_by(Mix.mix_number.asc())
        )
    )


async def _mix_id_by_number(client, club_id, user_id, number):
    """Resolve a mix's id via the API so we never read db_session mid-test."""
    resp = await client.get(_mixes_url(club_id), headers=_auth(user_id))
    assert resp.status_code == 200, resp.text
    for r in resp.json():
        if r["mix_number"] == number:
            return r["id"]
    raise AssertionError(f"mix {number} not found")


# --------------------------------------------------------------------------- #
# a. create_club with total_mixes=N -> N pending mixes, fully specified
# --------------------------------------------------------------------------- #


async def test_create_club_autogenerates_n_pending_mixes(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")

    resp = await _create_club(client, organizer.id, total_mixes=4, votes_per_player=7)
    assert resp.status_code == 201, resp.text
    club_id = uuid.UUID(resp.json()["id"])
    assert resp.json()["current_mix"] == 0

    mixes = await _mixes_for(db_session, club_id)
    assert [r.mix_number for r in mixes] == [1, 2, 3, 4]
    assert all(r.state == "pending" for r in mixes)
    assert all(r.theme is None for r in mixes)
    assert all(r.description is None for r in mixes)
    # votes_per_player propagates from the club to each mix.
    assert all(r.votes_per_player == 7 for r in mixes)

    # current_mix stays 0 on the persisted club row.
    db_session.expire_all()
    club = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert club.current_mix == 0


# --------------------------------------------------------------------------- #
# b. Omitting total_mixes -> 6 pending mixes (the new default)
# --------------------------------------------------------------------------- #


async def test_create_club_defaults_to_six_pending_mixes(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")

    resp = await _create_club(client, organizer.id)  # total_mixes omitted
    assert resp.status_code == 201, resp.text
    assert resp.json()["total_mixes"] == 6
    club_id = uuid.UUID(resp.json()["id"])

    mixes = await _mixes_for(db_session, club_id)
    assert [r.mix_number for r in mixes] == [1, 2, 3, 4, 5, 6]
    assert all(r.state == "pending" for r in mixes)


# --------------------------------------------------------------------------- #
# c. total_mixes bounds at create: 0 -> 422, 51 -> 422
# --------------------------------------------------------------------------- #


async def test_create_club_total_mixes_zero_is_422(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    resp = await _create_club(client, organizer.id, total_mixes=0)
    assert resp.status_code == 422, resp.text


async def test_create_club_total_mixes_above_max_is_422(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    resp = await _create_club(client, organizer.id, total_mixes=51)
    assert resp.status_code == 422, resp.text


async def test_create_club_total_mixes_at_max_is_allowed(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    resp = await _create_club(client, organizer.id, total_mixes=50)
    assert resp.status_code == 201, resp.text
    club_id = uuid.UUID(resp.json()["id"])
    mixes = await _mixes_for(db_session, club_id)
    assert len(mixes) == 50


# --------------------------------------------------------------------------- #
# d. Non-organizer members can list and see all pending mixes
# --------------------------------------------------------------------------- #


async def test_member_sees_all_pending_mixes(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    resp = await _create_club(client, organizer.id, total_mixes=3)
    club_id = uuid.UUID(resp.json()["id"])
    await _add_member(db_session, club_id, member)

    listed = await client.get(_mixes_url(club_id), headers=_auth(member.id))
    assert listed.status_code == 200, listed.text
    mixes = listed.json()
    assert [r["mix_number"] for r in mixes] == [1, 2, 3]
    assert all(r["state"] == "pending" for r in mixes)
    assert all(r["theme"] is None for r in mixes)


# --------------------------------------------------------------------------- #
# e. theme nullable round-trip: set theme+description while pending, then clear
# --------------------------------------------------------------------------- #


async def test_theme_set_and_cleared_while_pending(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    resp = await _create_club(client, organizer.id, total_mixes=2)
    club_id = uuid.UUID(resp.json()["id"])

    mix1_id = await _mix_id_by_number(client, club_id, organizer.id, 1)

    # Set theme + description on the pending mix.
    set_resp = await client.patch(
        f"/api/v1/mixes/{mix1_id}",
        json={"theme": "  golden hour  ", "description": "warm, late-day songs"},
        headers=_auth(organizer.id),
    )
    assert set_resp.status_code == 200, set_resp.text
    assert set_resp.json()["theme"] == "golden hour"  # trimmed
    assert set_resp.json()["description"] == "warm, late-day songs"

    # GET reflects the set values.
    got = await client.get(f"/api/v1/mixes/{mix1_id}", headers=_auth(organizer.id))
    assert got.json()["theme"] == "golden hour"
    assert got.json()["description"] == "warm, late-day songs"

    # Clear theme back to null (mix still pending — nullable column, no validator).
    clear_resp = await client.patch(
        f"/api/v1/mixes/{mix1_id}",
        json={"theme": None},
        headers=_auth(organizer.id),
    )
    assert clear_resp.status_code == 200, clear_resp.text
    assert clear_resp.json()["theme"] is None
    # description untouched (not provided).
    assert clear_resp.json()["description"] == "warm, late-day songs"


# --------------------------------------------------------------------------- #
# j. Regression: edit-lock + activation still hold on auto-generated mixes
# --------------------------------------------------------------------------- #


async def test_edit_lock_and_activation_on_autogen_mix(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    resp = await _create_club(client, organizer.id, total_mixes=2)
    club_id = uuid.UUID(resp.json()["id"])

    mix1_id = await _mix_id_by_number(client, club_id, organizer.id, 1)

    # Manually open mix 1: activation sets current_mix to 1.
    opened = await _advance(client, mix1_id, organizer.id, "open_submission")
    assert opened.status_code == 200, opened.text

    # theme is now locked (mix left pending).
    locked = await client.patch(
        f"/api/v1/mixes/{mix1_id}",
        json={"theme": "too late"},
        headers=_auth(organizer.id),
    )
    assert locked.status_code == 409, locked.text
    assert "locked" in locked.json()["detail"]

    # current_mix advanced to 1 on activation (asserted last so all API calls
    # finish before db_session is read — async expire_all/greenlet convention).
    db_session.expire_all()
    club = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert club.current_mix == 1
