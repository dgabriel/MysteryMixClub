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
from app.models.round import Round
from app.models.user import User

LEAGUES_URL = "/api/v1/leagues"

# The full league object key set, matching POST /leagues.
_LEAGUE_KEYS = {
    "id",
    "name",
    "description",
    "organizer_id",
    "total_rounds",
    "votes_per_player",
    "songs_per_submission",
    "current_round",
    "default_vibe_mode",
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


async def _create_league_via_api(client, user_id, *, total_rounds=6, votes_per_player=5):
    """Create a league through the POST endpoint so its round slate auto-generates."""
    resp = await client.post(
        LEAGUES_URL,
        headers=_auth_header(user_id),
        json={
            "name": "Reconcile League",
            "total_rounds": total_rounds,
            "votes_per_player": votes_per_player,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _round_numbers(db_session, league_id):
    rounds = list(
        await db_session.scalars(
            select(Round).where(Round.league_id == league_id).order_by(Round.round_number.asc())
        )
    )
    return [r.round_number for r in rounds]


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


async def test_total_rounds_above_max_returns_422(client, db_session):
    # Same upper bound as create: the reconcile grow path must not bulk-insert an
    # unbounded slate.
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)

    resp = await client.patch(
        _patch_url(league.id),
        headers=_auth_header(organizer.id),
        json={"total_rounds": 51},
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


# ========================================================================== #
# Round-slate reconciliation on total_rounds change (MYS-62)
# ========================================================================== #


async def test_grow_total_rounds_appends_pending_rounds(client, db_session):
    # f. N -> N+2 appends two new pending rounds with the next sequential numbers.
    organizer = await _seed_user(db_session)
    league = await _create_league_via_api(client, organizer.id, total_rounds=4)
    league_id = uuid.UUID(league["id"])

    resp = await client.patch(
        _patch_url(league_id),
        headers=_auth_header(organizer.id),
        json={"total_rounds": 6},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_rounds"] == 6

    db_session.expire_all()
    assert await _round_numbers(db_session, league_id) == [1, 2, 3, 4, 5, 6]
    # The two appended rounds are pending with no theme/description and inherit
    # the league's votes_per_player.
    appended = list(
        await db_session.scalars(
            select(Round)
            .where(Round.league_id == league_id, Round.round_number > 4)
            .order_by(Round.round_number.asc())
        )
    )
    assert [r.round_number for r in appended] == [5, 6]
    assert all(r.state == "pending" for r in appended)
    assert all(r.theme is None and r.description is None for r in appended)
    assert all(r.votes_per_player == 5 for r in appended)


async def test_shrink_total_rounds_deletes_trailing_pending_rounds(client, db_session):
    # g. N -> N-2 deletes the trailing two (all-pending) rounds.
    organizer = await _seed_user(db_session)
    league = await _create_league_via_api(client, organizer.id, total_rounds=6)
    league_id = uuid.UUID(league["id"])

    resp = await client.patch(
        _patch_url(league_id),
        headers=_auth_header(organizer.id),
        json={"total_rounds": 4},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_rounds"] == 4

    db_session.expire_all()
    assert await _round_numbers(db_session, league_id) == [1, 2, 3, 4]


async def test_shrink_blocked_when_a_removed_round_has_started(client, db_session):
    # h. A trailing round that is NOT pending (here: closed) cannot be removed by
    #    a shrink. Set up the slate directly so a started round sits ABOVE the new
    #    total while current_round stays below it, isolating the started-round
    #    guard from the current_round guard. Expect 409, slate + total_rounds
    #    intact. All db_session writes happen up front (committed) before any API
    #    call, per the async expire_all/greenlet conventions.
    organizer = await _seed_user(db_session)
    league = League(
        name="Started Trailing",
        organizer_id=organizer.id,
        total_rounds=4,
        votes_per_player=3,
        current_round=1,
    )
    db_session.add(league)
    await db_session.flush()
    league_id = league.id
    db_session.add(LeagueMember(league_id=league_id, user_id=organizer.id))
    # Rounds 1 (open_submission) and 2 (closed) have started; 3 and 4 are pending.
    db_session.add(Round(league_id=league_id, round_number=1, state="open_submission"))
    db_session.add(Round(league_id=league_id, round_number=2, state="closed"))
    db_session.add(Round(league_id=league_id, round_number=3, state="pending"))
    db_session.add(Round(league_id=league_id, round_number=4, state="pending"))
    await db_session.commit()

    # Shrink to 2 keeps current_round (1) satisfied, but rounds > 2 are 3,4 (both
    # pending) -> that alone would be allowed. Shrink to 1 instead: rounds > 1 are
    # 2 (closed/started), 3, 4 -> the started round 2 blocks removal. current_round
    # is 1, so new_total (1) is NOT below current_round; only the started-round
    # guard fires.
    resp = await client.patch(
        _patch_url(league_id),
        headers=_auth_header(organizer.id),
        json={"total_rounds": 1},
    )
    assert resp.status_code == 409, resp.text
    assert "already started" in resp.json()["detail"]

    # Unchanged: total_rounds still 4 and all four rounds remain.
    db_session.expire_all()
    persisted = await db_session.scalar(select(League).where(League.id == league_id))
    assert persisted.total_rounds == 4
    assert await _round_numbers(db_session, league_id) == [1, 2, 3, 4]


async def test_total_rounds_below_current_round_returns_409(client, db_session):
    # i. new_total < current_round -> 409, slate unchanged. Seed a league already
    #    on round 2 (round 1 closed, round 2 open) directly, up front, so the only
    #    API call is the failing PATCH.
    organizer = await _seed_user(db_session)
    league = League(
        name="Mid-flight",
        organizer_id=organizer.id,
        total_rounds=4,
        votes_per_player=3,
        current_round=2,
    )
    db_session.add(league)
    await db_session.flush()
    league_id = league.id
    db_session.add(LeagueMember(league_id=league_id, user_id=organizer.id))
    db_session.add(Round(league_id=league_id, round_number=1, state="closed"))
    db_session.add(Round(league_id=league_id, round_number=2, state="open_submission"))
    db_session.add(Round(league_id=league_id, round_number=3, state="pending"))
    db_session.add(Round(league_id=league_id, round_number=4, state="pending"))
    await db_session.commit()

    resp = await client.patch(
        _patch_url(league_id),
        headers=_auth_header(organizer.id),
        json={"total_rounds": 1},
    )
    assert resp.status_code == 409, resp.text
    assert "current_round" in resp.json()["detail"]

    db_session.expire_all()
    persisted = await db_session.scalar(select(League).where(League.id == league_id))
    assert persisted.total_rounds == 4
    assert await _round_numbers(db_session, league_id) == [1, 2, 3, 4]
