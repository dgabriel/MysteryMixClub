"""Tests for MYS-159: deadline schema for datetime-based mix closing.

Covers two surfaces:

* the per-club deadline windows (``submission_window_hours`` /
  ``voting_window_hours``) on the Clubs create/update API — defaults,
  persistence, the 4..168 hour bound (422), and explicit-null rejection; and
* the deadline *stamping* done in ``advance_mix_state`` when a mix enters
  ``open_submission`` / ``open_voting`` (manual PATCH and the auto-opened next
  mix on close), including the "don't clobber a manually set deadline" rule.

Mixes are stamped only through the PATCH state machine, so these tests drive the
auto-generated pending slate created by ``POST /clubs`` rather than the
single-create endpoint (which is born ``open_submission`` and never stamps).

Windows are hour-granular (min 4h, max 168h; default 72h = 3 days) as of the
2026-07-02 rework. See technical-design.md §6 (clubs, mixes) and the MYS-159
migration ``c7d2e9f1a4b8_deadline_schema``.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.user import User

CLUBS_URL = "/api/v1/clubs"

# Tolerance for "deadline is about now + N hours": the server stamps with its own
# datetime.now, the test computes its expected with a slightly later one, so a
# couple of minutes of slack absorbs the request round-trip without letting a
# wrong window count sneak past.
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


async def _create_club(client, user_id: uuid.UUID, **overrides) -> dict:
    """Create a club via the API so its pending mix slate auto-generates."""
    body = {"name": "Deadline Club", "total_mixes": 3, "votes_per_player": 3}
    body.update(overrides)
    resp = await client.post(CLUBS_URL, headers=_auth(user_id), json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _mixes(client, club_id, user_id) -> list[dict]:
    resp = await client.get(f"{CLUBS_URL}/{club_id}/mixes", headers=_auth(user_id))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _mix_by_number(client, club_id, user_id, number: int) -> dict:
    return next(r for r in await _mixes(client, club_id, user_id) if r["mix_number"] == number)


async def _patch_mix(client, mix_id, user_id, **body) -> dict:
    resp = await client.patch(f"/api/v1/mixes/{mix_id}", json=body, headers=_auth(user_id))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _assert_about_hours(deadline_iso: str | None, expected_hours: int) -> None:
    """Assert an ISO deadline string is ~ now + expected_hours (within tolerance)."""
    assert deadline_iso is not None, "expected a stamped deadline, got null"
    deadline = datetime.fromisoformat(deadline_iso)
    expected = datetime.now(timezone.utc) + timedelta(hours=expected_hours)
    delta = abs((deadline - expected).total_seconds())
    assert delta < _TOL_SECONDS, (
        f"deadline {deadline} is {delta:.0f}s from expected {expected} (≈ now + {expected_hours}h)"
    )


# ========================================================================== #
# Club API — deadline-window fields
# ========================================================================== #


async def test_create_defaults_windows_to_72(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id)  # no window fields supplied
    assert data["submission_window_hours"] == 72
    assert data["voting_window_hours"] == 72


async def test_create_with_explicit_windows_persisted(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id, submission_window_hours=6, voting_window_hours=100)
    assert data["submission_window_hours"] == 6
    assert data["voting_window_hours"] == 100

    club_id = uuid.UUID(data["id"])
    db_session.expire_all()
    persisted = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert persisted.submission_window_hours == 6
    assert persisted.voting_window_hours == 100


async def test_create_accepts_min_boundary_4(client, db_session):
    # 4h is the inclusive minimum — accepted on both fields.
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id, submission_window_hours=4, voting_window_hours=4)
    assert data["submission_window_hours"] == 4
    assert data["voting_window_hours"] == 4


async def test_create_accepts_max_boundary_168(client, db_session):
    # 168h is the inclusive maximum — accepted on both fields.
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id, submission_window_hours=168, voting_window_hours=168)
    assert data["submission_window_hours"] == 168
    assert data["voting_window_hours"] == 168


async def test_create_submission_window_below_min_returns_422(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.post(
        CLUBS_URL,
        headers=_auth(user.id),
        json={"name": "L", "submission_window_hours": 3},
    )
    assert resp.status_code == 422, resp.text


async def test_create_submission_window_above_max_returns_422(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.post(
        CLUBS_URL,
        headers=_auth(user.id),
        json={"name": "L", "submission_window_hours": 169},
    )
    assert resp.status_code == 422, resp.text


async def test_create_voting_window_below_min_returns_422(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.post(
        CLUBS_URL,
        headers=_auth(user.id),
        json={"name": "L", "voting_window_hours": 3},
    )
    assert resp.status_code == 422, resp.text


async def test_create_voting_window_above_max_returns_422(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.post(
        CLUBS_URL,
        headers=_auth(user.id),
        json={"name": "L", "voting_window_hours": 169},
    )
    assert resp.status_code == 422, resp.text


async def test_patch_windows_updates_and_persists(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id)
    club_id = uuid.UUID(data["id"])

    resp = await client.patch(
        f"{CLUBS_URL}/{club_id}",
        headers=_auth(user.id),
        json={"submission_window_hours": 12, "voting_window_hours": 168},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["submission_window_hours"] == 12
    assert body["voting_window_hours"] == 168

    db_session.expire_all()
    persisted = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert persisted.submission_window_hours == 12
    assert persisted.voting_window_hours == 168


async def test_patch_accepts_min_boundary_4(client, db_session):
    # 4h is the inclusive minimum — accepted on patch for both fields.
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id)
    resp = await client.patch(
        f"{CLUBS_URL}/{data['id']}",
        headers=_auth(user.id),
        json={"submission_window_hours": 4, "voting_window_hours": 4},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["submission_window_hours"] == 4
    assert body["voting_window_hours"] == 4


async def test_patch_accepts_max_boundary_168(client, db_session):
    # 168h is the inclusive maximum — accepted on patch for both fields.
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id)
    resp = await client.patch(
        f"{CLUBS_URL}/{data['id']}",
        headers=_auth(user.id),
        json={"submission_window_hours": 168, "voting_window_hours": 168},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["submission_window_hours"] == 168
    assert body["voting_window_hours"] == 168


async def test_patch_submission_window_below_min_returns_422(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id)
    resp = await client.patch(
        f"{CLUBS_URL}/{data['id']}",
        headers=_auth(user.id),
        json={"submission_window_hours": 3},
    )
    assert resp.status_code == 422, resp.text


async def test_patch_voting_window_above_max_returns_422(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id)
    resp = await client.patch(
        f"{CLUBS_URL}/{data['id']}",
        headers=_auth(user.id),
        json={"voting_window_hours": 169},
    )
    assert resp.status_code == 422, resp.text


async def test_patch_explicit_null_submission_window_returns_422(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id)
    resp = await client.patch(
        f"{CLUBS_URL}/{data['id']}",
        headers=_auth(user.id),
        json={"submission_window_hours": None},
    )
    assert resp.status_code == 422, resp.text


async def test_patch_explicit_null_voting_window_returns_422(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id)
    resp = await client.patch(
        f"{CLUBS_URL}/{data['id']}",
        headers=_auth(user.id),
        json={"voting_window_hours": None},
    )
    assert resp.status_code == 422, resp.text


# ========================================================================== #
# Deadline stamping on state transitions
# ========================================================================== #


async def test_open_submission_stamps_submission_deadline(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id)  # default 72/72
    club_id = data["id"]
    r1 = await _mix_by_number(client, club_id, user.id, 1)
    assert r1["state"] == "pending"
    assert r1["submission_deadline"] is None

    opened = await _patch_mix(client, r1["id"], user.id, state="open_submission")
    assert opened["state"] == "open_submission"
    _assert_about_hours(opened["submission_deadline"], 72)
    # Voting deadline is only stamped when voting opens.
    assert opened["voting_deadline"] is None


async def test_open_voting_stamps_voting_deadline(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id)  # default 72/72
    club_id = data["id"]
    r1 = await _mix_by_number(client, club_id, user.id, 1)

    await _patch_mix(client, r1["id"], user.id, state="open_submission")
    voting = await _patch_mix(client, r1["id"], user.id, state="open_voting")
    assert voting["state"] == "open_voting"
    _assert_about_hours(voting["voting_deadline"], 72)


async def test_open_submission_does_not_clobber_manual_deadline(client, db_session):
    # An organizer who sets a submission_deadline explicitly while the mix is
    # pending keeps it when the mix opens (MYS-159 no-clobber).
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id)  # default 72h window
    club_id = data["id"]
    r1 = await _mix_by_number(client, club_id, user.id, 1)

    manual = datetime.now(timezone.utc) + timedelta(hours=240)
    await _patch_mix(client, r1["id"], user.id, submission_deadline=manual.isoformat())
    opened = await _patch_mix(client, r1["id"], user.id, state="open_submission")
    # Still ~240h out, not the 72h club default — the manual value stuck.
    _assert_about_hours(opened["submission_deadline"], 240)


async def test_open_voting_does_not_clobber_manual_voting_deadline(client, db_session):
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id)  # default 72h window
    club_id = data["id"]
    r1 = await _mix_by_number(client, club_id, user.id, 1)

    await _patch_mix(client, r1["id"], user.id, state="open_submission")
    manual = datetime.now(timezone.utc) + timedelta(hours=288)
    await _patch_mix(client, r1["id"], user.id, voting_deadline=manual.isoformat())
    voting = await _patch_mix(client, r1["id"], user.id, state="open_voting")
    _assert_about_hours(voting["voting_deadline"], 288)


# ========================================================================== #
# Auto-open path — the next mix gets its own submission deadline
# ========================================================================== #


async def test_closing_nonfinal_mix_stamps_next_mix_submission_deadline(client, db_session):
    # total_mixes=2 so mix 1 is non-final: closing it auto-opens mix 2, which
    # must get its own submission_deadline stamped from the club window.
    user = await _seed_user(db_session)
    data = await _create_club(client, user.id, total_mixes=2)  # default 72h
    club_id = data["id"]
    r1 = await _mix_by_number(client, club_id, user.id, 1)

    await _patch_mix(client, r1["id"], user.id, state="open_submission")
    await _patch_mix(client, r1["id"], user.id, state="open_voting")
    closed = await _patch_mix(client, r1["id"], user.id, state="closed")
    assert closed["state"] == "closed"

    r2 = await _mix_by_number(client, club_id, user.id, 2)
    assert r2["state"] == "open_submission"
    _assert_about_hours(r2["submission_deadline"], 72)


# ========================================================================== #
# Custom club config drives the stamp windows
# ========================================================================== #


async def test_custom_windows_reflected_in_stamps(client, db_session):
    user = await _seed_user(db_session)
    # 102h = 4 days 6 hours (a non-day-aligned window); 4h = the minimum.
    data = await _create_club(client, user.id, submission_window_hours=102, voting_window_hours=4)
    club_id = data["id"]
    r1 = await _mix_by_number(client, club_id, user.id, 1)

    opened = await _patch_mix(client, r1["id"], user.id, state="open_submission")
    _assert_about_hours(opened["submission_deadline"], 102)

    voting = await _patch_mix(client, r1["id"], user.id, state="open_voting")
    _assert_about_hours(voting["voting_deadline"], 4)


async def test_next_mix_stamp_uses_club_window_not_default(client, db_session):
    # The auto-opened mix's deadline must follow the club's custom window too,
    # not a hardcoded default.
    user = await _seed_user(db_session)
    data = await _create_club(
        client, user.id, total_mixes=2, submission_window_hours=48, voting_window_hours=120
    )
    club_id = data["id"]
    r1 = await _mix_by_number(client, club_id, user.id, 1)

    await _patch_mix(client, r1["id"], user.id, state="open_submission")
    await _patch_mix(client, r1["id"], user.id, state="open_voting")
    await _patch_mix(client, r1["id"], user.id, state="closed")

    r2 = await _mix_by_number(client, club_id, user.id, 2)
    _assert_about_hours(r2["submission_deadline"], 48)
