"""Tests for MYS-62: rounds auto-generated at league creation.

When a league is created the backend inserts its full slate of ``pending``
rounds (one per ``total_rounds``, default 6), numbered 1..N with no theme or
description and the league's ``votes_per_player``. ``current_round`` stays 0
until a round is opened. theme is now nullable end-to-end, so a pending round's
theme/description can be set and later cleared while it is still pending.

Reuses the seed/auth helpers in ``test_rounds.py`` for users and membership, but
creates leagues through the POST endpoint so the auto-generation runs.
"""

import uuid

from sqlalchemy import select

from app.models.league import League
from app.models.round import Round

from tests.test_rounds import (  # reuse established helpers
    _add_member,
    _advance,
    _auth,
    _rounds_url,
    _seed_user,
)

LEAGUES_URL = "/api/v1/clubs"


async def _create_league(client, user_id, *, name="Autogen League", **fields):
    body = {"name": name}
    body.update(fields)
    return await client.post(LEAGUES_URL, json=body, headers=_auth(user_id))


async def _rounds_for(db_session, league_id):
    return list(
        await db_session.scalars(
            select(Round).where(Round.league_id == league_id).order_by(Round.round_number.asc())
        )
    )


async def _round_id_by_number(client, league_id, user_id, number):
    """Resolve a round's id via the API so we never read db_session mid-test."""
    resp = await client.get(_rounds_url(league_id), headers=_auth(user_id))
    assert resp.status_code == 200, resp.text
    for r in resp.json():
        if r["mix_number"] == number:
            return r["id"]
    raise AssertionError(f"round {number} not found")


# --------------------------------------------------------------------------- #
# a. create_league with total_rounds=N -> N pending rounds, fully specified
# --------------------------------------------------------------------------- #


async def test_create_league_autogenerates_n_pending_rounds(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")

    resp = await _create_league(client, organizer.id, total_rounds=4, votes_per_player=7)
    assert resp.status_code == 201, resp.text
    league_id = uuid.UUID(resp.json()["id"])
    assert resp.json()["current_mix"] == 0

    rounds = await _rounds_for(db_session, league_id)
    assert [r.round_number for r in rounds] == [1, 2, 3, 4]
    assert all(r.state == "pending" for r in rounds)
    assert all(r.theme is None for r in rounds)
    assert all(r.description is None for r in rounds)
    # votes_per_player propagates from the league to each round.
    assert all(r.votes_per_player == 7 for r in rounds)

    # current_round stays 0 on the persisted league row.
    db_session.expire_all()
    league = await db_session.scalar(select(League).where(League.id == league_id))
    assert league.current_round == 0


# --------------------------------------------------------------------------- #
# b. Omitting total_rounds -> 6 pending rounds (the new default)
# --------------------------------------------------------------------------- #


async def test_create_league_defaults_to_six_pending_rounds(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")

    resp = await _create_league(client, organizer.id)  # total_rounds omitted
    assert resp.status_code == 201, resp.text
    assert resp.json()["total_mixes"] == 6
    league_id = uuid.UUID(resp.json()["id"])

    rounds = await _rounds_for(db_session, league_id)
    assert [r.round_number for r in rounds] == [1, 2, 3, 4, 5, 6]
    assert all(r.state == "pending" for r in rounds)


# --------------------------------------------------------------------------- #
# c. total_rounds bounds at create: 0 -> 422, 51 -> 422
# --------------------------------------------------------------------------- #


async def test_create_league_total_rounds_zero_is_422(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    resp = await _create_league(client, organizer.id, total_rounds=0)
    assert resp.status_code == 422, resp.text


async def test_create_league_total_rounds_above_max_is_422(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    resp = await _create_league(client, organizer.id, total_rounds=51)
    assert resp.status_code == 422, resp.text


async def test_create_league_total_rounds_at_max_is_allowed(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    resp = await _create_league(client, organizer.id, total_rounds=50)
    assert resp.status_code == 201, resp.text
    league_id = uuid.UUID(resp.json()["id"])
    rounds = await _rounds_for(db_session, league_id)
    assert len(rounds) == 50


# --------------------------------------------------------------------------- #
# d. Non-organizer members can list and see all pending rounds
# --------------------------------------------------------------------------- #


async def test_member_sees_all_pending_rounds(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    resp = await _create_league(client, organizer.id, total_rounds=3)
    league_id = uuid.UUID(resp.json()["id"])
    await _add_member(db_session, league_id, member)

    listed = await client.get(_rounds_url(league_id), headers=_auth(member.id))
    assert listed.status_code == 200, listed.text
    rounds = listed.json()
    assert [r["mix_number"] for r in rounds] == [1, 2, 3]
    assert all(r["state"] == "pending" for r in rounds)
    assert all(r["theme"] is None for r in rounds)


# --------------------------------------------------------------------------- #
# e. theme nullable round-trip: set theme+description while pending, then clear
# --------------------------------------------------------------------------- #


async def test_theme_set_and_cleared_while_pending(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    resp = await _create_league(client, organizer.id, total_rounds=2)
    league_id = uuid.UUID(resp.json()["id"])

    round1_id = await _round_id_by_number(client, league_id, organizer.id, 1)

    # Set theme + description on the pending round.
    set_resp = await client.patch(
        f"/api/v1/mixes/{round1_id}",
        json={"theme": "  golden hour  ", "description": "warm, late-day songs"},
        headers=_auth(organizer.id),
    )
    assert set_resp.status_code == 200, set_resp.text
    assert set_resp.json()["theme"] == "golden hour"  # trimmed
    assert set_resp.json()["description"] == "warm, late-day songs"

    # GET reflects the set values.
    got = await client.get(f"/api/v1/mixes/{round1_id}", headers=_auth(organizer.id))
    assert got.json()["theme"] == "golden hour"
    assert got.json()["description"] == "warm, late-day songs"

    # Clear theme back to null (round still pending — nullable column, no validator).
    clear_resp = await client.patch(
        f"/api/v1/mixes/{round1_id}",
        json={"theme": None},
        headers=_auth(organizer.id),
    )
    assert clear_resp.status_code == 200, clear_resp.text
    assert clear_resp.json()["theme"] is None
    # description untouched (not provided).
    assert clear_resp.json()["description"] == "warm, late-day songs"


# --------------------------------------------------------------------------- #
# j. Regression: edit-lock + activation still hold on auto-generated rounds
# --------------------------------------------------------------------------- #


async def test_edit_lock_and_activation_on_autogen_round(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    resp = await _create_league(client, organizer.id, total_rounds=2)
    league_id = uuid.UUID(resp.json()["id"])

    round1_id = await _round_id_by_number(client, league_id, organizer.id, 1)

    # Manually open round 1: activation sets current_round to 1.
    opened = await _advance(client, round1_id, organizer.id, "open_submission")
    assert opened.status_code == 200, opened.text

    # theme is now locked (round left pending).
    locked = await client.patch(
        f"/api/v1/mixes/{round1_id}",
        json={"theme": "too late"},
        headers=_auth(organizer.id),
    )
    assert locked.status_code == 409, locked.text
    assert "locked" in locked.json()["detail"]

    # current_round advanced to 1 on activation (asserted last so all API calls
    # finish before db_session is read — async expire_all/greenlet convention).
    db_session.expire_all()
    league = await db_session.scalar(select(League).where(League.id == league_id))
    assert league.current_round == 1
