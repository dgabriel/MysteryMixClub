"""Tests for MYS-159: deadline schema for datetime-based round closing.

Covers two surfaces:

* the per-league deadline windows (``submission_deadline_days`` /
  ``voting_deadline_days``) on the Leagues create/update API — defaults,
  persistence, the 1..14 bound (422), and explicit-null rejection; and
* the deadline *stamping* done in ``advance_round_state`` when a round enters
  ``open_submission`` / ``open_voting`` (manual PATCH and the auto-opened next
  round on close), including the "don't clobber a manually set deadline" rule.

Rounds are stamped only through the PATCH state machine, so these tests drive the
auto-generated pending slate created by ``POST /leagues`` rather than the
single-create endpoint (which is born ``open_submission`` and never stamps).

See technical-design.md §6 (leagues, rounds) and the MYS-159 migration
``c7d2e9f1a4b8_deadline_schema``.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.league import League
from app.models.user import User

LEAGUES_URL = "/api/v1/leagues"

# Tolerance for "deadline is about now + N days": the server stamps with its own
# datetime.now, the test computes its expected with a slightly later one, so a
# couple of minutes of slack absorbs the request round-trip without letting a
# wrong day count (whole days apart) sneak past.
_TOL_SECONDS = 120


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str = "org@example.com", name: str = "Org") -> User:
    user = User(email=email, display_name=name)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _create_league(client, user_id: uuid.UUID, **overrides) -> dict:
    """Create a league via the API so its pending round slate auto-generates."""
    body = {"name": "Deadline League", "total_rounds": 3, "votes_per_player": 3}
    body.update(overrides)
    resp = await client.post(LEAGUES_URL, headers=_auth(user_id), json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _rounds(client, league_id, user_id) -> list[dict]:
    resp = await client.get(f"{LEAGUES_URL}/{league_id}/rounds", headers=_auth(user_id))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _round_by_number(client, league_id, user_id, number: int) -> dict:
    return next(r for r in await _rounds(client, league_id, user_id) if r["round_number"] == number)


async def _patch_round(client, round_id, user_id, **body) -> dict:
    resp = await client.patch(f"/api/v1/rounds/{round_id}", json=body, headers=_auth(user_id))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _assert_about_days(deadline_iso: str | None, expected_days: int) -> None:
    """Assert an ISO deadline string is ~ now + expected_days (within tolerance)."""
    assert deadline_iso is not None, "expected a stamped deadline, got null"
    deadline = datetime.fromisoformat(deadline_iso)
    expected = datetime.now(timezone.utc) + timedelta(days=expected_days)
    delta = abs((deadline - expected).total_seconds())
    assert delta < _TOL_SECONDS, (
        f"deadline {deadline} is {delta:.0f}s from expected {expected} (≈ now + {expected_days}d)"
    )


# ========================================================================== #
# League API — deadline-day fields
# ========================================================================== #


async def test_create_defaults_deadline_days_to_3(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_league(client, user.id)  # no deadline fields supplied
    assert data["submission_deadline_days"] == 3
    assert data["voting_deadline_days"] == 3


async def test_create_with_explicit_deadline_days_persisted(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_league(client, user.id, submission_deadline_days=5, voting_deadline_days=7)
    assert data["submission_deadline_days"] == 5
    assert data["voting_deadline_days"] == 7

    league_id = uuid.UUID(data["id"])
    db_session.expire_all()
    persisted = await db_session.scalar(select(League).where(League.id == league_id))
    assert persisted.submission_deadline_days == 5
    assert persisted.voting_deadline_days == 7


async def test_create_submission_deadline_days_zero_returns_422(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.post(
        LEAGUES_URL,
        headers=_auth(user.id),
        json={"name": "L", "submission_deadline_days": 0},
    )
    assert resp.status_code == 422, resp.text


async def test_create_submission_deadline_days_above_max_returns_422(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.post(
        LEAGUES_URL,
        headers=_auth(user.id),
        json={"name": "L", "submission_deadline_days": 15},
    )
    assert resp.status_code == 422, resp.text


async def test_create_voting_deadline_days_zero_returns_422(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.post(
        LEAGUES_URL,
        headers=_auth(user.id),
        json={"name": "L", "voting_deadline_days": 0},
    )
    assert resp.status_code == 422, resp.text


async def test_create_voting_deadline_days_above_max_returns_422(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.post(
        LEAGUES_URL,
        headers=_auth(user.id),
        json={"name": "L", "voting_deadline_days": 15},
    )
    assert resp.status_code == 422, resp.text


async def test_patch_deadline_days_updates_and_persists(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_league(client, user.id)
    league_id = uuid.UUID(data["id"])

    resp = await client.patch(
        f"{LEAGUES_URL}/{league_id}",
        headers=_auth(user.id),
        json={"submission_deadline_days": 2, "voting_deadline_days": 10},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["submission_deadline_days"] == 2
    assert body["voting_deadline_days"] == 10

    db_session.expire_all()
    persisted = await db_session.scalar(select(League).where(League.id == league_id))
    assert persisted.submission_deadline_days == 2
    assert persisted.voting_deadline_days == 10


async def test_patch_submission_deadline_days_zero_returns_422(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_league(client, user.id)
    resp = await client.patch(
        f"{LEAGUES_URL}/{data['id']}",
        headers=_auth(user.id),
        json={"submission_deadline_days": 0},
    )
    assert resp.status_code == 422, resp.text


async def test_patch_voting_deadline_days_above_max_returns_422(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_league(client, user.id)
    resp = await client.patch(
        f"{LEAGUES_URL}/{data['id']}",
        headers=_auth(user.id),
        json={"voting_deadline_days": 15},
    )
    assert resp.status_code == 422, resp.text


async def test_patch_explicit_null_submission_deadline_days_returns_422(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_league(client, user.id)
    resp = await client.patch(
        f"{LEAGUES_URL}/{data['id']}",
        headers=_auth(user.id),
        json={"submission_deadline_days": None},
    )
    assert resp.status_code == 422, resp.text


async def test_patch_explicit_null_voting_deadline_days_returns_422(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_league(client, user.id)
    resp = await client.patch(
        f"{LEAGUES_URL}/{data['id']}",
        headers=_auth(user.id),
        json={"voting_deadline_days": None},
    )
    assert resp.status_code == 422, resp.text


# ========================================================================== #
# Deadline stamping on state transitions
# ========================================================================== #


async def test_open_submission_stamps_submission_deadline(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_league(client, user.id)  # default 3/3
    league_id = data["id"]
    r1 = await _round_by_number(client, league_id, user.id, 1)
    assert r1["state"] == "pending"
    assert r1["submission_deadline"] is None

    opened = await _patch_round(client, r1["id"], user.id, state="open_submission")
    assert opened["state"] == "open_submission"
    _assert_about_days(opened["submission_deadline"], 3)
    # Voting deadline is only stamped when voting opens.
    assert opened["voting_deadline"] is None


async def test_open_voting_stamps_voting_deadline(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_league(client, user.id)  # default 3/3
    league_id = data["id"]
    r1 = await _round_by_number(client, league_id, user.id, 1)

    await _patch_round(client, r1["id"], user.id, state="open_submission")
    voting = await _patch_round(client, r1["id"], user.id, state="open_voting")
    assert voting["state"] == "open_voting"
    _assert_about_days(voting["voting_deadline"], 3)


async def test_open_submission_does_not_clobber_manual_deadline(client, db_session):
    # An organizer who sets a submission_deadline explicitly while the round is
    # pending keeps it when the round opens (MYS-159 no-clobber).
    user = await _seed_user(db_session)
    data = await _create_league(client, user.id)  # default 3d window
    league_id = data["id"]
    r1 = await _round_by_number(client, league_id, user.id, 1)

    manual = datetime.now(timezone.utc) + timedelta(days=10)
    await _patch_round(client, r1["id"], user.id, submission_deadline=manual.isoformat())
    opened = await _patch_round(client, r1["id"], user.id, state="open_submission")
    # Still ~10 days out, not the 3-day league default — the manual value stuck.
    _assert_about_days(opened["submission_deadline"], 10)


async def test_open_voting_does_not_clobber_manual_voting_deadline(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_league(client, user.id)  # default 3d window
    league_id = data["id"]
    r1 = await _round_by_number(client, league_id, user.id, 1)

    await _patch_round(client, r1["id"], user.id, state="open_submission")
    manual = datetime.now(timezone.utc) + timedelta(days=12)
    await _patch_round(client, r1["id"], user.id, voting_deadline=manual.isoformat())
    voting = await _patch_round(client, r1["id"], user.id, state="open_voting")
    _assert_about_days(voting["voting_deadline"], 12)


# ========================================================================== #
# Auto-open path — the next round gets its own submission deadline
# ========================================================================== #


async def test_closing_nonfinal_round_stamps_next_round_submission_deadline(client, db_session):
    # total_rounds=2 so round 1 is non-final: closing it auto-opens round 2, which
    # must get its own submission_deadline stamped from the league window.
    user = await _seed_user(db_session)
    data = await _create_league(client, user.id, total_rounds=2)  # default 3d
    league_id = data["id"]
    r1 = await _round_by_number(client, league_id, user.id, 1)

    await _patch_round(client, r1["id"], user.id, state="open_submission")
    await _patch_round(client, r1["id"], user.id, state="open_voting")
    closed = await _patch_round(client, r1["id"], user.id, state="closed")
    assert closed["state"] == "closed"

    r2 = await _round_by_number(client, league_id, user.id, 2)
    assert r2["state"] == "open_submission"
    _assert_about_days(r2["submission_deadline"], 3)


# ========================================================================== #
# Custom league config drives the stamp windows
# ========================================================================== #


async def test_custom_deadline_days_reflected_in_stamps(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_league(client, user.id, submission_deadline_days=1, voting_deadline_days=7)
    league_id = data["id"]
    r1 = await _round_by_number(client, league_id, user.id, 1)

    opened = await _patch_round(client, r1["id"], user.id, state="open_submission")
    _assert_about_days(opened["submission_deadline"], 1)

    voting = await _patch_round(client, r1["id"], user.id, state="open_voting")
    _assert_about_days(voting["voting_deadline"], 7)


async def test_next_round_stamp_uses_league_window_not_default(client, db_session):
    # The auto-opened round's deadline must follow the league's custom window too,
    # not a hardcoded default.
    user = await _seed_user(db_session)
    data = await _create_league(
        client, user.id, total_rounds=2, submission_deadline_days=2, voting_deadline_days=5
    )
    league_id = data["id"]
    r1 = await _round_by_number(client, league_id, user.id, 1)

    await _patch_round(client, r1["id"], user.id, state="open_submission")
    await _patch_round(client, r1["id"], user.id, state="open_voting")
    await _patch_round(client, r1["id"], user.id, state="closed")

    r2 = await _round_by_number(client, league_id, user.id, 2)
    _assert_about_days(r2["submission_deadline"], 2)
