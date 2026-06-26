"""Tests for MYS-14: DELETE /api/v1/leagues/{league_id}/members/{user_id}.

TDD-first: written before the endpoint exists, so they are expected to FAIL
(red) until the developer implements the route on the existing leagues router.

Covers auth (401), not-found (404), organizer-only authorization (403),
organizer-removes-self conflict (409), removing a non-member / already-removed
member (404), the happy-path soft delete (204 + removed_at set), and the
integration proof that a removed member loses access (their subsequent invite
generation is rejected by the existing active-member gate). See
technical-design.md §6 (league_members) and §7 (Leagues API: DELETE
/leagues/:id/members/:userId — organizer only).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.auth.jwt import create_access_token
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


def _remove_url(league_id, user_id) -> str:
    return f"/api/v1/leagues/{league_id}/members/{user_id}"


def _invites_url(league_id) -> str:
    return f"/api/v1/leagues/{league_id}/invites"


# ========================================================================== #
# Auth
# ========================================================================== #


async def test_unauthenticated_remove_returns_401(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)

    resp = await client.delete(_remove_url(league.id, member.id))

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


# ========================================================================== #
# Not found
# ========================================================================== #


async def test_remove_from_unknown_league_returns_404(client, db_session):
    organizer = await _seed_user(db_session)

    resp = await client.delete(
        _remove_url(uuid.uuid4(), uuid.uuid4()),
        headers=_auth_header(organizer.id),
    )

    assert resp.status_code == 404, resp.text


# ========================================================================== #
# Authorization (organizer only)
# ========================================================================== #


async def test_non_organizer_caller_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)
    target = await _seed_user(db_session, email="target@example.com", display_name="Target")
    await _seed_member(db_session, league, target)

    # A non-organizer member tries to remove another member.
    resp = await client.delete(
        _remove_url(league.id, target.id),
        headers=_auth_header(member.id),
    )

    assert resp.status_code == 403, resp.text


# ========================================================================== #
# Organizer removing self (409)
# ========================================================================== #


async def test_organizer_removes_self_returns_409_and_still_active(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)

    resp = await client.delete(
        _remove_url(league.id, organizer.id),
        headers=_auth_header(organizer.id),
    )

    assert resp.status_code == 409, resp.text

    league_id = league.id
    organizer_id = organizer.id
    db_session.expire_all()

    membership = await db_session.scalar(
        select(LeagueMember).where(
            LeagueMember.league_id == league_id,
            LeagueMember.user_id == organizer_id,
        )
    )
    assert membership is not None
    assert membership.removed_at is None


# ========================================================================== #
# Target not an active member (404)
# ========================================================================== #


async def test_remove_non_member_returns_404(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    stranger = await _seed_user(db_session, email="stranger@example.com", display_name="Stranger")

    resp = await client.delete(
        _remove_url(league.id, stranger.id),
        headers=_auth_header(organizer.id),
    )

    assert resp.status_code == 404, resp.text


async def test_remove_already_removed_member_returns_404(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member, removed_at=datetime.now(timezone.utc))

    resp = await client.delete(
        _remove_url(league.id, member.id),
        headers=_auth_header(organizer.id),
    )

    assert resp.status_code == 404, resp.text


# ========================================================================== #
# Happy path — soft delete (204)
# ========================================================================== #


async def test_organizer_removes_active_member_returns_204_and_soft_deletes(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)

    resp = await client.delete(
        _remove_url(league.id, member.id),
        headers=_auth_header(organizer.id),
    )

    assert resp.status_code == 204, resp.text
    assert resp.content == b""

    league_id = league.id
    member_id = member.id
    db_session.expire_all()

    rows = (
        await db_session.scalars(
            select(LeagueMember).where(
                LeagueMember.league_id == league_id,
                LeagueMember.user_id == member_id,
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].removed_at is not None


# ========================================================================== #
# Integration — removed member loses access
# ========================================================================== #


async def test_removed_member_loses_access_to_invites(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)

    # Sanity: while active, the member CAN generate an invite.
    pre = await client.post(_invites_url(league.id), headers=_auth_header(member.id))
    assert pre.status_code == 201, pre.text

    # Organizer removes the member.
    removed = await client.delete(
        _remove_url(league.id, member.id),
        headers=_auth_header(organizer.id),
    )
    assert removed.status_code == 204, removed.text

    # The removed member can no longer generate invites — the active-member gate
    # now rejects them.
    post = await client.post(_invites_url(league.id), headers=_auth_header(member.id))
    assert post.status_code == 403, post.text
