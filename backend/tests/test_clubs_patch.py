"""Tests for MYS-14: PATCH /api/v1/clubs/{club_id} (update club).

TDD-first: written before the endpoint exists, so they are expected to FAIL
(red) until the developer implements the route on the existing clubs router.

Covers auth (401), not-found (404), organizer-only authorization (403 for both
non-organizer members and non-member strangers), state/mixes conflicts (409),
the partial-update happy path with persistence, and request-validation 422s.
See technical-design.md §6 (clubs, club_members) and §7 (Clubs API:
PATCH /clubs/:id — organizer only).
"""

import uuid

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.user import User

CLUBS_URL = "/api/v1/clubs"

# The full club object key set, matching POST /clubs.
_CLUB_KEYS = {
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


async def _seed_club(db_session, organizer: User, **overrides) -> Club:
    """Insert and commit a Club with the organizer as an active member."""
    defaults = {
        "name": "Summer Bangers",
        "description": "A club for hot tracks",
        "organizer_id": organizer.id,
        "total_mixes": 6,
        "votes_per_player": 5,
        "current_mix": 0,
        "state": "active",
    }
    defaults.update(overrides)
    club = Club(**defaults)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(club)
    return club


async def _seed_member(db_session, club: Club, user: User, **overrides) -> ClubMember:
    """Insert and commit a ClubMember row, returning it."""
    defaults = {"club_id": club.id, "user_id": user.id}
    defaults.update(overrides)
    member = ClubMember(**defaults)
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _patch_url(club_id) -> str:
    return f"/api/v1/clubs/{club_id}"


async def _create_club_via_api(client, user_id, *, total_mixes=6, votes_per_player=5):
    """Create a club through the POST endpoint so its mix slate auto-generates."""
    resp = await client.post(
        CLUBS_URL,
        headers=_auth_header(user_id),
        json={
            "name": "Reconcile Club",
            "total_mixes": total_mixes,
            "votes_per_player": votes_per_player,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _mix_numbers(db_session, club_id):
    mixes = list(
        await db_session.scalars(
            select(Mix).where(Mix.club_id == club_id).order_by(Mix.mix_number.asc())
        )
    )
    return [r.mix_number for r in mixes]


# ========================================================================== #
# Auth
# ========================================================================== #


async def test_unauthenticated_patch_returns_401(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.patch(_patch_url(club.id), json={"name": "New Name"})

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


# ========================================================================== #
# Not found
# ========================================================================== #


async def test_patch_unknown_club_returns_404(client, db_session):
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
    club = await _seed_club(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, club, member)  # active, non-organizer

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(member.id),
        json={"name": "New Name"},
    )

    assert resp.status_code == 403, resp.text


async def test_non_member_stranger_patch_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    stranger = await _seed_user(db_session, email="stranger@example.com", display_name="Stranger")

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(stranger.id),
        json={"name": "New Name"},
    )

    assert resp.status_code == 403, resp.text


# ========================================================================== #
# Happy path — response shape & persistence
# ========================================================================== #


async def test_organizer_updates_all_fields_returns_200_full_shape_and_persists(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(
        db_session, organizer, name="Old Name", description="Old desc", total_mixes=6
    )

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"name": "  Brand New  ", "description": "Fresh desc", "total_mixes": 8},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) == _CLUB_KEYS
    assert data["name"] == "Brand New"  # trimmed
    assert data["description"] == "Fresh desc"
    assert data["total_mixes"] == 8

    club_id = club.id
    db_session.expire_all()

    persisted = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert persisted.name == "Brand New"
    assert persisted.description == "Fresh desc"
    assert persisted.total_mixes == 8


async def test_partial_update_only_name_leaves_other_fields_untouched(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(
        db_session, organizer, name="Old Name", description="Keep me", total_mixes=6
    )

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"name": "Renamed"},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name"] == "Renamed"
    assert data["description"] == "Keep me"
    assert data["total_mixes"] == 6

    club_id = club.id
    db_session.expire_all()

    persisted = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert persisted.name == "Renamed"
    assert persisted.description == "Keep me"
    assert persisted.total_mixes == 6


async def test_extend_mixes_returns_200(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer, total_mixes=6, current_mix=2)

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"total_mixes": 10},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["total_mixes"] == 10


async def test_shorten_to_equal_current_mix_returns_200(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer, total_mixes=6, current_mix=3)

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"total_mixes": 3},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["total_mixes"] == 3


# ========================================================================== #
# Conflicts (409)
# ========================================================================== #


async def test_shorten_below_current_mix_returns_409_and_unchanged(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer, total_mixes=6, current_mix=4)

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"total_mixes": 2},
    )

    assert resp.status_code == 409, resp.text

    club_id = club.id
    db_session.expire_all()

    persisted = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert persisted.total_mixes == 6


async def test_completed_club_edit_returns_409_and_unchanged(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer, name="Old Name", state="complete")

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"name": "New Name"},
    )

    assert resp.status_code == 409, resp.text

    club_id = club.id
    db_session.expire_all()

    persisted = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert persisted.name == "Old Name"


# ========================================================================== #
# Validation rejections (422)
# ========================================================================== #


async def test_empty_name_returns_422(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"name": ""},
    )

    assert resp.status_code == 422, resp.text


async def test_whitespace_only_name_returns_422(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"name": "   "},
    )

    assert resp.status_code == 422, resp.text


async def test_name_too_long_returns_422(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"name": "x" * 101},
    )

    assert resp.status_code == 422, resp.text


async def test_total_mixes_below_one_returns_422(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"total_mixes": 0},
    )

    assert resp.status_code == 422, resp.text


async def test_total_mixes_above_max_returns_422(client, db_session):
    # Same upper bound as create: the reconcile grow path must not bulk-insert an
    # unbounded slate.
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"total_mixes": 51},
    )

    assert resp.status_code == 422, resp.text


async def test_explicit_null_name_returns_422(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"name": None},
    )

    assert resp.status_code == 422, resp.text


async def test_explicit_null_total_mixes_returns_422(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"total_mixes": None},
    )

    assert resp.status_code == 422, resp.text


# ========================================================================== #
# description explicit null clears it
# ========================================================================== #


async def test_explicit_null_description_clears_it_returns_200(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer, description="Has a description")

    resp = await client.patch(
        _patch_url(club.id),
        headers=_auth_header(organizer.id),
        json={"description": None},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] is None

    club_id = club.id
    db_session.expire_all()

    persisted = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert persisted.description is None


# ========================================================================== #
# Mix-slate reconciliation on total_mixes change (MYS-62)
# ========================================================================== #


async def test_grow_total_mixes_appends_pending_mixes(client, db_session):
    # f. N -> N+2 appends two new pending mixes with the next sequential numbers.
    organizer = await _seed_user(db_session)
    club = await _create_club_via_api(client, organizer.id, total_mixes=4)
    club_id = uuid.UUID(club["id"])

    resp = await client.patch(
        _patch_url(club_id),
        headers=_auth_header(organizer.id),
        json={"total_mixes": 6},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_mixes"] == 6

    db_session.expire_all()
    assert await _mix_numbers(db_session, club_id) == [1, 2, 3, 4, 5, 6]
    # The two appended mixes are pending with no theme/description and inherit
    # the club's votes_per_player.
    appended = list(
        await db_session.scalars(
            select(Mix)
            .where(Mix.club_id == club_id, Mix.mix_number > 4)
            .order_by(Mix.mix_number.asc())
        )
    )
    assert [r.mix_number for r in appended] == [5, 6]
    assert all(r.state == "pending" for r in appended)
    assert all(r.theme is None and r.description is None for r in appended)
    assert all(r.votes_per_player == 5 for r in appended)


async def test_shrink_total_mixes_deletes_trailing_pending_mixes(client, db_session):
    # g. N -> N-2 deletes the trailing two (all-pending) mixes.
    organizer = await _seed_user(db_session)
    club = await _create_club_via_api(client, organizer.id, total_mixes=6)
    club_id = uuid.UUID(club["id"])

    resp = await client.patch(
        _patch_url(club_id),
        headers=_auth_header(organizer.id),
        json={"total_mixes": 4},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_mixes"] == 4

    db_session.expire_all()
    assert await _mix_numbers(db_session, club_id) == [1, 2, 3, 4]


async def test_shrink_blocked_when_a_removed_mix_has_started(client, db_session):
    # h. A trailing mix that is NOT pending (here: closed) cannot be removed by
    #    a shrink. Set up the slate directly so a started mix sits ABOVE the new
    #    total while current_mix stays below it, isolating the started-mix
    #    guard from the current_mix guard. Expect 409, slate + total_mixes
    #    intact. All db_session writes happen up front (committed) before any API
    #    call, per the async expire_all/greenlet conventions.
    organizer = await _seed_user(db_session)
    club = Club(
        name="Started Trailing",
        organizer_id=organizer.id,
        total_mixes=4,
        votes_per_player=3,
        current_mix=1,
    )
    db_session.add(club)
    await db_session.flush()
    club_id = club.id
    db_session.add(ClubMember(club_id=club_id, user_id=organizer.id))
    # Mixes 1 (open_submission) and 2 (closed) have started; 3 and 4 are pending.
    db_session.add(Mix(club_id=club_id, mix_number=1, state="open_submission"))
    db_session.add(Mix(club_id=club_id, mix_number=2, state="closed"))
    db_session.add(Mix(club_id=club_id, mix_number=3, state="pending"))
    db_session.add(Mix(club_id=club_id, mix_number=4, state="pending"))
    await db_session.commit()

    # Shrink to 2 keeps current_mix (1) satisfied, but mixes > 2 are 3,4 (both
    # pending) -> that alone would be allowed. Shrink to 1 instead: mixes > 1 are
    # 2 (closed/started), 3, 4 -> the started mix 2 blocks removal. current_mix
    # is 1, so new_total (1) is NOT below current_mix; only the started-mix
    # guard fires.
    resp = await client.patch(
        _patch_url(club_id),
        headers=_auth_header(organizer.id),
        json={"total_mixes": 1},
    )
    assert resp.status_code == 409, resp.text
    assert "already started" in resp.json()["detail"]

    # Unchanged: total_mixes still 4 and all four mixes remain.
    db_session.expire_all()
    persisted = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert persisted.total_mixes == 4
    assert await _mix_numbers(db_session, club_id) == [1, 2, 3, 4]


async def test_total_mixes_below_current_mix_returns_409(client, db_session):
    # i. new_total < current_mix -> 409, slate unchanged. Seed a club already
    #    on mix 2 (mix 1 closed, mix 2 open) directly, up front, so the only
    #    API call is the failing PATCH.
    organizer = await _seed_user(db_session)
    club = Club(
        name="Mid-flight",
        organizer_id=organizer.id,
        total_mixes=4,
        votes_per_player=3,
        current_mix=2,
    )
    db_session.add(club)
    await db_session.flush()
    club_id = club.id
    db_session.add(ClubMember(club_id=club_id, user_id=organizer.id))
    db_session.add(Mix(club_id=club_id, mix_number=1, state="closed"))
    db_session.add(Mix(club_id=club_id, mix_number=2, state="open_submission"))
    db_session.add(Mix(club_id=club_id, mix_number=3, state="pending"))
    db_session.add(Mix(club_id=club_id, mix_number=4, state="pending"))
    await db_session.commit()

    resp = await client.patch(
        _patch_url(club_id),
        headers=_auth_header(organizer.id),
        json={"total_mixes": 1},
    )
    assert resp.status_code == 409, resp.text
    assert "below the current mix" in resp.json()["detail"]

    db_session.expire_all()
    persisted = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert persisted.total_mixes == 4
    assert await _mix_numbers(db_session, club_id) == [1, 2, 3, 4]
