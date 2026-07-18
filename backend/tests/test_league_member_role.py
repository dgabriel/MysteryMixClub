"""Tests for MYS-99: PATCH /api/v1/leagues/{league_id}/members/{user_id}/role.

Covers the co-organizer promote/demote endpoint: auth (401), not-found (404,
both unknown league and a target who isn't an active member), authorization
(403 for a plain member caller), the organizer-target conflict (409, both
promote and demote attempts), and the happy paths for promotion and demotion —
including the capability check that a promoted co-organizer can then perform
an organizer-only action (updating the league) that a plain member cannot, and
loses it again once demoted.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.jobs.purge_accounts import hard_delete_users
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.user import User

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


def _role_url(league_id, user_id) -> str:
    return f"/api/v1/leagues/{league_id}/members/{user_id}/role"


def _league_url(league_id) -> str:
    return f"/api/v1/leagues/{league_id}"


# ========================================================================== #
# Auth
# ========================================================================== #


async def test_unauthenticated_role_change_returns_401(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)

    resp = await client.patch(_role_url(league.id, member.id), json={"role": "admin"})

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


# ========================================================================== #
# Not found
# ========================================================================== #


async def test_role_change_unknown_league_returns_404(client, db_session):
    organizer = await _seed_user(db_session)

    resp = await client.patch(
        _role_url(uuid.uuid4(), uuid.uuid4()),
        headers=_auth_header(organizer.id),
        json={"role": "admin"},
    )

    assert resp.status_code == 404, resp.text


async def test_role_change_target_never_joined_returns_404(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    stranger = await _seed_user(db_session, email="stranger@example.com", display_name="Stranger")

    resp = await client.patch(
        _role_url(league.id, stranger.id),
        headers=_auth_header(organizer.id),
        json={"role": "admin"},
    )

    assert resp.status_code == 404, resp.text


async def test_role_change_target_removed_member_returns_404(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    removed = await _seed_user(db_session, email="removed@example.com", display_name="Removed")
    await _seed_member(db_session, league, removed, removed_at=datetime.now(timezone.utc))

    resp = await client.patch(
        _role_url(league.id, removed.id),
        headers=_auth_header(organizer.id),
        json={"role": "admin"},
    )

    assert resp.status_code == 404, resp.text


# ========================================================================== #
# Authorization (403) — plain member cannot change roles
# ========================================================================== #


async def test_plain_member_role_change_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    caller = await _seed_user(db_session, email="caller@example.com", display_name="Caller")
    await _seed_member(db_session, league, caller)
    target = await _seed_user(db_session, email="target@example.com", display_name="Target")
    await _seed_member(db_session, league, target)

    resp = await client.patch(
        _role_url(league.id, target.id),
        headers=_auth_header(caller.id),
        json={"role": "admin"},
    )

    assert resp.status_code == 403, resp.text


async def test_non_member_stranger_role_change_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    stranger = await _seed_user(db_session, email="stranger@example.com", display_name="Stranger")
    target = await _seed_user(db_session, email="target@example.com", display_name="Target")
    await _seed_member(db_session, league, target)

    resp = await client.patch(
        _role_url(league.id, target.id),
        headers=_auth_header(stranger.id),
        json={"role": "admin"},
    )

    assert resp.status_code == 403, resp.text


# ========================================================================== #
# Conflict (409) — the fixed organizer's row can't be changed here
# ========================================================================== #


async def test_promoting_the_organizer_returns_409(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)

    resp = await client.patch(
        _role_url(league.id, organizer.id),
        headers=_auth_header(organizer.id),
        json={"role": "admin"},
    )

    assert resp.status_code == 409, resp.text


async def test_demoting_the_organizer_returns_409(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    # A co-organizer attempts to demote the fixed organizer.
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, league, co_organizer, role="admin")

    resp = await client.patch(
        _role_url(league.id, organizer.id),
        headers=_auth_header(co_organizer.id),
        json={"role": "member"},
    )

    assert resp.status_code == 409, resp.text


# ========================================================================== #
# Happy path — promotion
# ========================================================================== #


async def test_organizer_promotes_member_to_admin_returns_200_and_is_admin_true(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)

    resp = await client.patch(
        _role_url(league.id, member.id),
        headers=_auth_header(organizer.id),
        json={"role": "admin"},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["user_id"] == str(member.id)
    assert data["is_admin"] is True
    assert data["is_organizer"] is False


async def test_promoted_co_organizer_can_perform_organizer_only_action(client, db_session):
    # A promoted co-organizer gains full parity: they can update the league,
    # which a plain member cannot (MYS-99).
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer, name="Old Name")
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)

    promote = await client.patch(
        _role_url(league.id, member.id),
        headers=_auth_header(organizer.id),
        json={"role": "admin"},
    )
    assert promote.status_code == 200, promote.text

    # Before promotion this member would 403; now it succeeds.
    resp = await client.patch(
        _league_url(league.id),
        headers=_auth_header(member.id),
        json={"name": "Renamed by Co-Organizer"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Renamed by Co-Organizer"


# ========================================================================== #
# Happy path — demotion
# ========================================================================== #


async def test_admin_demotes_another_admin_back_to_member(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    co_organizer_a = await _seed_user(db_session, email="co-a@example.com", display_name="CoA")
    await _seed_member(db_session, league, co_organizer_a, role="admin")
    co_organizer_b = await _seed_user(db_session, email="co-b@example.com", display_name="CoB")
    await _seed_member(db_session, league, co_organizer_b, role="admin")

    # co_organizer_a (an existing admin, not the fixed organizer) demotes co_organizer_b.
    resp = await client.patch(
        _role_url(league.id, co_organizer_b.id),
        headers=_auth_header(co_organizer_a.id),
        json={"role": "member"},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["is_admin"] is False
    assert data["is_organizer"] is False


async def test_demoted_co_organizer_loses_organizer_only_capability(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer, name="Old Name")
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, league, co_organizer, role="admin")

    # Sanity: while an admin, the co-organizer CAN update the league.
    pre = await client.patch(
        _league_url(league.id),
        headers=_auth_header(co_organizer.id),
        json={"name": "Renamed While Admin"},
    )
    assert pre.status_code == 200, pre.text

    demote = await client.patch(
        _role_url(league.id, co_organizer.id),
        headers=_auth_header(organizer.id),
        json={"role": "member"},
    )
    assert demote.status_code == 200, demote.text
    assert demote.json()["is_admin"] is False

    # Now demoted, the same action is forbidden.
    resp = await client.patch(
        _league_url(league.id),
        headers=_auth_header(co_organizer.id),
        json={"name": "Should Not Apply"},
    )

    assert resp.status_code == 403, resp.text


# ========================================================================== #
# Zero-effective-admins lockout guard (purged organizer, MYS-99 follow-up)
# ========================================================================== #


async def test_demoting_last_admin_with_purged_organizer_returns_409(client, db_session):
    """When the fixed organizer has been hard-purged, ``leagues.organizer_id``
    is nulled and the organizer's own ``league_members`` row is deleted (see
    ``app.jobs.purge_accounts.hard_delete_users``). The league's only
    remaining admin-capable member is then the sole co-organizer; demoting
    them would leave the league permanently unadministrable, so it 409s.
    """
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, league, co_organizer, role="admin")

    league_id = league.id
    co_organizer_id = co_organizer.id

    # Simulate the scheduled purge job hard-deleting the organizer's account.
    await hard_delete_users(db_session, [organizer.id], [organizer.email])
    await db_session.commit()

    league = await db_session.scalar(select(League).where(League.id == league_id))
    assert league is not None
    assert league.organizer_id is None, "purge must null organizer_id for the guard to apply"

    # The sole remaining admin is now the only caller who can even reach this
    # endpoint (the fixed organizer is gone) — self-demotion must 409.
    resp = await client.patch(
        _role_url(league_id, co_organizer_id),
        headers=_auth_header(co_organizer_id),
        json={"role": "member"},
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "cannot remove the last admin from a club with no organizer"


async def test_demoting_an_admin_with_purged_organizer_and_another_admin_succeeds(
    client, db_session
):
    """Companion to the guard above, proving it's precisely scoped: with a
    second active admin present, demoting one of them still succeeds even
    with the organizer purged, because the league retains an admin-capable
    member afterward. The guard must not overreach into this case.
    """
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    co_organizer_a = await _seed_user(db_session, email="co-a@example.com", display_name="CoA")
    await _seed_member(db_session, league, co_organizer_a, role="admin")
    co_organizer_b = await _seed_user(db_session, email="co-b@example.com", display_name="CoB")
    await _seed_member(db_session, league, co_organizer_b, role="admin")

    league_id = league.id
    co_organizer_a_id = co_organizer_a.id
    co_organizer_b_id = co_organizer_b.id

    await hard_delete_users(db_session, [organizer.id], [organizer.email])
    await db_session.commit()

    league = await db_session.scalar(select(League).where(League.id == league_id))
    assert league is not None
    assert league.organizer_id is None, "purge must null organizer_id for this to be a fair test"

    resp = await client.patch(
        _role_url(league_id, co_organizer_b_id),
        headers=_auth_header(co_organizer_a_id),
        json={"role": "member"},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["is_admin"] is False
    assert data["is_organizer"] is False


async def test_demoting_last_admin_when_other_admin_is_soft_deleted_returns_409(client, db_session):
    """Companion to the purged-organizer guard above: a soft-deleted (but not
    yet hard-purged) co-organizer still has a live ``league_members`` row with
    ``role == "admin"``, but they're not a functioning admin any more. The
    ``other_admin`` query now joins ``User`` and requires
    ``User.deleted_at.is_(None)``, so this stale row must not count — self-
    demoting the sole real admin must still 409, even though the pre-fix query
    would have found B's row and incorrectly let it through.
    """
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    admin_a = await _seed_user(db_session, email="admin-a@example.com", display_name="AdminA")
    await _seed_member(db_session, league, admin_a, role="admin")
    admin_b = await _seed_user(db_session, email="admin-b@example.com", display_name="AdminB")
    await _seed_member(db_session, league, admin_b, role="admin")

    league_id = league.id
    admin_a_id = admin_a.id
    admin_b_id = admin_b.id

    # Simulate the scheduled purge job hard-deleting the organizer's account.
    await hard_delete_users(db_session, [organizer.id], [organizer.email])
    await db_session.commit()

    league = await db_session.scalar(select(League).where(League.id == league_id))
    assert league is not None
    assert league.organizer_id is None, "purge must null organizer_id for this to be a fair test"

    # Soft-delete admin B, matching exactly what DELETE /users/me sets.
    admin_b_row = await db_session.scalar(select(User).where(User.id == admin_b_id))
    assert admin_b_row is not None
    admin_b_row.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    # Admin A self-demotes. B's row is still role == "admin" and not removed_at,
    # but B is soft-deleted, so B must not count as a real other admin.
    resp = await client.patch(
        _role_url(league_id, admin_a_id),
        headers=_auth_header(admin_a_id),
        json={"role": "member"},
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "cannot remove the last admin from a club with no organizer"


# ========================================================================== #
# Validation
# ========================================================================== #


async def test_invalid_role_value_returns_422(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)

    resp = await client.patch(
        _role_url(league.id, member.id),
        headers=_auth_header(organizer.id),
        json={"role": "superadmin"},
    )

    assert resp.status_code == 422, resp.text


# ========================================================================== #
# Regression — the fixed organizer retains all existing behavior
# ========================================================================== #


async def test_organizer_can_still_promote_and_demote_after_co_organizers_exist(client, db_session):
    # Nothing about adding co-organizer support narrows the fixed organizer's
    # own access to the role endpoint against other members.
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, league, co_organizer, role="admin")
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)

    promote = await client.patch(
        _role_url(league.id, member.id),
        headers=_auth_header(organizer.id),
        json={"role": "admin"},
    )
    assert promote.status_code == 200, promote.text
    assert promote.json()["is_admin"] is True

    demote = await client.patch(
        _role_url(league.id, co_organizer.id),
        headers=_auth_header(organizer.id),
        json={"role": "member"},
    )
    assert demote.status_code == 200, demote.text
    assert demote.json()["is_admin"] is False
