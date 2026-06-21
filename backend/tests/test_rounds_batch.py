"""Tests for MYS-62: pre-created rounds.

Covers the batch create endpoint (``POST /leagues/:id/rounds:batch``), the
pending->open_submission manual activation with the single-active-round guard,
auto-opening the next pending round when a non-final round closes, league
completion when the final round closes, the theme/description edit lock once a
round leaves ``pending``, and ``description`` round-tripping through both create
paths and the response.

Shares the seed/helper conventions in ``test_rounds.py`` (re-imported here so the
two files stay independent but consistent).
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.league import League
from app.models.round import Round

from tests.test_rounds import (  # reuse the established helpers/fixtures
    _add_member,
    _advance,
    _auth,
    _create_round,
    _rounds_url,
    _seed_league,
    _seed_user,
)


def _batch_url(league_id: uuid.UUID) -> str:
    return f"/api/v1/leagues/{league_id}/rounds:batch"


async def _create_batch(client, league_id, organizer_id, rounds):
    return await client.post(
        _batch_url(league_id), json={"rounds": rounds}, headers=_auth(organizer_id)
    )


# --------------------------------------------------------------------------- #
# 1. Batch create — happy path
# --------------------------------------------------------------------------- #


async def test_batch_create_happy_path(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer, total_rounds=1)
    league_id = league.id

    resp = await _create_batch(
        client,
        league_id,
        organizer.id,
        [
            {"theme": "  golden hour  ", "description": "warm, late-day songs"},
            {"theme": "rainy day", "description": "songs for grey skies"},
            {"theme": "midnight drive"},
        ],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # All three created, numbered 1..N in payload order, all pending.
    assert [r["round_number"] for r in body] == [1, 2, 3]
    assert all(r["state"] == "pending" for r in body)
    assert body[0]["theme"] == "golden hour"  # trimmed
    # description persisted (and round-trips through the response).
    assert body[0]["description"] == "warm, late-day songs"
    assert body[1]["description"] == "songs for grey skies"
    assert body[2]["description"] is None
    assert all(r["closed_at"] is None for r in body)

    # league.total_rounds is reset to the slate size; no round is active yet.
    db_session.expire_all()
    league = await db_session.scalar(select(League).where(League.id == league_id))
    assert league.total_rounds == 3
    assert league.current_round == 0
    assert league.state == "active"


async def test_batch_create_persists_to_db(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    league_id = league.id

    resp = await _create_batch(
        client,
        league_id,
        organizer.id,
        [{"theme": "one"}, {"theme": "two"}],
    )
    assert resp.status_code == 201, resp.text

    db_session.expire_all()
    rounds = list(
        await db_session.scalars(
            select(Round).where(Round.league_id == league_id).order_by(Round.round_number.asc())
        )
    )
    assert [r.round_number for r in rounds] == [1, 2]
    assert all(r.state == "pending" for r in rounds)


# --------------------------------------------------------------------------- #
# 2. Batch create — guards
# --------------------------------------------------------------------------- #


async def test_batch_create_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    resp = await client.post(_batch_url(league.id), json={"rounds": [{"theme": "x"}]})
    assert resp.status_code == 401


async def test_batch_create_non_organizer_forbidden(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    league = await _seed_league(db_session, organizer)
    await _add_member(db_session, league.id, member)

    resp = await _create_batch(client, league.id, member.id, [{"theme": "x"}])
    assert resp.status_code == 403


async def test_batch_create_empty_list_rejected(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)

    resp = await _create_batch(client, league.id, organizer.id, [])
    assert resp.status_code == 422, resp.text


async def test_batch_create_missing_rounds_key_rejected(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)

    resp = await client.post(_batch_url(league.id), json={}, headers=_auth(organizer.id))
    assert resp.status_code == 422, resp.text


async def test_batch_create_league_already_has_rounds_conflicts(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    # A single-created round already exists.
    assert (await _create_round(client, league.id, organizer.id)).status_code == 201

    resp = await _create_batch(client, league.id, organizer.id, [{"theme": "x"}])
    assert resp.status_code == 409, resp.text
    assert "already has rounds" in resp.json()["detail"]


async def test_batch_create_twice_conflicts(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)

    first = await _create_batch(client, league.id, organizer.id, [{"theme": "x"}])
    assert first.status_code == 201

    second = await _create_batch(client, league.id, organizer.id, [{"theme": "y"}])
    assert second.status_code == 409, second.text
    assert "already has rounds" in second.json()["detail"]


async def test_batch_create_on_complete_league_conflicts(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer, total_rounds=1)
    # Drive the league to complete via a single round.
    rid = (await _create_round(client, league.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    await _advance(client, rid, organizer.id, "closed")

    resp = await _create_batch(client, league.id, organizer.id, [{"theme": "x"}])
    assert resp.status_code == 409, resp.text
    assert "complete" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# 3. Members can list and see the pending rounds
# --------------------------------------------------------------------------- #


async def test_member_can_list_pending_rounds(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    league = await _seed_league(db_session, organizer)
    await _add_member(db_session, league.id, member)
    await _create_batch(
        client, league.id, organizer.id, [{"theme": "one"}, {"theme": "two"}, {"theme": "three"}]
    )

    resp = await client.get(_rounds_url(league.id), headers=_auth(member.id))
    assert resp.status_code == 200, resp.text
    rounds = resp.json()
    assert [r["round_number"] for r in rounds] == [1, 2, 3]
    assert all(r["state"] == "pending" for r in rounds)


# --------------------------------------------------------------------------- #
# 4. Manual open + single-active-round guard
# --------------------------------------------------------------------------- #


async def test_manual_open_first_round_sets_current_round(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    league_id = league.id
    body = (
        await _create_batch(client, league_id, organizer.id, [{"theme": "one"}, {"theme": "two"}])
    ).json()
    rid1 = body[0]["id"]

    resp = await _advance(client, rid1, organizer.id, "open_submission")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "open_submission"

    db_session.expire_all()
    league = await db_session.scalar(select(League).where(League.id == league_id))
    assert league.current_round == 1


async def test_opening_second_round_while_one_active_conflicts(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    body = (
        await _create_batch(client, league.id, organizer.id, [{"theme": "one"}, {"theme": "two"}])
    ).json()
    rid1, rid2 = body[0]["id"], body[1]["id"]

    assert (await _advance(client, rid1, organizer.id, "open_submission")).status_code == 200

    resp = await _advance(client, rid2, organizer.id, "open_submission")
    assert resp.status_code == 409, resp.text
    assert "already active" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# 5. Auto-open on close
# --------------------------------------------------------------------------- #


async def test_closing_round_auto_opens_next_pending(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    league_id = league.id
    body = (
        await _create_batch(
            client,
            league_id,
            organizer.id,
            [{"theme": "one"}, {"theme": "two"}, {"theme": "three"}],
        )
    ).json()
    rid1, rid2 = body[0]["id"], body[1]["id"]

    # Open and run round 1 through to closed.
    assert (await _advance(client, rid1, organizer.id, "open_submission")).status_code == 200
    assert (await _advance(client, rid1, organizer.id, "open_voting")).status_code == 200
    assert (await _advance(client, rid1, organizer.id, "closed")).status_code == 200

    # Round 2 (round_number+1) auto-opens to open_submission; current_round moves.
    r2 = await client.get(f"/api/v1/rounds/{rid2}", headers=_auth(organizer.id))
    assert r2.status_code == 200
    assert r2.json()["state"] == "open_submission"

    db_session.expire_all()
    league = await db_session.scalar(select(League).where(League.id == league_id))
    assert league.current_round == 2
    assert league.state == "active"


async def test_closing_round_leaves_later_rounds_pending(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    body = (
        await _create_batch(
            client,
            league.id,
            organizer.id,
            [{"theme": "one"}, {"theme": "two"}, {"theme": "three"}],
        )
    ).json()
    rid1, rid3 = body[0]["id"], body[2]["id"]

    await _advance(client, rid1, organizer.id, "open_submission")
    await _advance(client, rid1, organizer.id, "open_voting")
    await _advance(client, rid1, organizer.id, "closed")

    # Round 3 stays pending — only the immediate next round opens.
    r3 = await client.get(f"/api/v1/rounds/{rid3}", headers=_auth(organizer.id))
    assert r3.json()["state"] == "pending"


# --------------------------------------------------------------------------- #
# 6. Closing the final round completes the league, opens nothing
# --------------------------------------------------------------------------- #


async def test_closing_final_round_completes_league(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    league_id = league.id
    body = (
        await _create_batch(client, league_id, organizer.id, [{"theme": "one"}, {"theme": "two"}])
    ).json()
    rid1, rid2 = body[0]["id"], body[1]["id"]

    # Round 1 closes -> round 2 auto-opens.
    await _advance(client, rid1, organizer.id, "open_submission")
    await _advance(client, rid1, organizer.id, "open_voting")
    await _advance(client, rid1, organizer.id, "closed")

    # Round 2 is the final round; closing it completes the league.
    await _advance(client, rid2, organizer.id, "open_voting")
    closed = await _advance(client, rid2, organizer.id, "closed")
    assert closed.status_code == 200, closed.text

    db_session.expire_all()
    league = await db_session.scalar(select(League).where(League.id == league_id))
    assert league.state == "complete"
    assert league.completed_at is not None

    # No further round exists to open beyond the final one.
    rounds = list(
        await db_session.scalars(
            select(Round).where(Round.league_id == league_id).order_by(Round.round_number.asc())
        )
    )
    assert [r.state for r in rounds] == ["closed", "closed"]


# --------------------------------------------------------------------------- #
# 7. Edit lock (theme / description) — and deadlines stay editable
# --------------------------------------------------------------------------- #


async def test_edit_theme_and_description_while_pending(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    rid = (await _create_batch(client, league.id, organizer.id, [{"theme": "one"}])).json()[0]["id"]

    resp = await client.patch(
        f"/api/v1/rounds/{rid}",
        json={"theme": "reworked theme", "description": "reworked description"},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["theme"] == "reworked theme"
    assert resp.json()["description"] == "reworked description"


async def test_edit_theme_on_open_round_rejected(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    rid = (await _create_batch(client, league.id, organizer.id, [{"theme": "one"}])).json()[0]["id"]
    await _advance(client, rid, organizer.id, "open_submission")

    resp = await client.patch(
        f"/api/v1/rounds/{rid}", json={"theme": "too late"}, headers=_auth(organizer.id)
    )
    assert resp.status_code == 409, resp.text
    assert "locked" in resp.json()["detail"]


async def test_edit_description_on_open_round_rejected(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    rid = (await _create_batch(client, league.id, organizer.id, [{"theme": "one"}])).json()[0]["id"]
    await _advance(client, rid, organizer.id, "open_submission")

    resp = await client.patch(
        f"/api/v1/rounds/{rid}", json={"description": "too late"}, headers=_auth(organizer.id)
    )
    assert resp.status_code == 409, resp.text
    assert "locked" in resp.json()["detail"]


async def test_edit_deadline_on_open_round_still_allowed(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    rid = (await _create_batch(client, league.id, organizer.id, [{"theme": "one"}])).json()[0]["id"]
    await _advance(client, rid, organizer.id, "open_submission")

    deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    resp = await client.patch(
        f"/api/v1/rounds/{rid}",
        json={"submission_deadline": deadline},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["submission_deadline"] is not None


# --------------------------------------------------------------------------- #
# description round-trips through single create too
# --------------------------------------------------------------------------- #


async def test_description_round_trips_through_single_create(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)

    resp = await _create_round(
        client, league.id, organizer.id, theme="solo", description="a single-created round"
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["description"] == "a single-created round"
