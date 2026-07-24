"""Tests for DELETE /api/v1/clubs/{club_id}/members/{user_id}.

Covers the organizer-remove path (MYS-14) and the self-leave path (MYS-97):
auth (401), not-found (404), organizer-only authorization (403),
organizer-removes-self conflict (409), removing a non-member / already-removed
member (404), happy-path soft delete (204 + removed_at set), integration proof
that a removed member loses access, and the full self-leave flow (member leaves
their own club, blocked for organizers).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.club_member import ClubMember
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


def _remove_url(club_id, user_id) -> str:
    return f"/api/v1/clubs/{club_id}/members/{user_id}"


def _invites_url(club_id) -> str:
    return f"/api/v1/clubs/{club_id}/invites"


# ========================================================================== #
# Auth
# ========================================================================== #


async def test_unauthenticated_remove_returns_401(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, club, member)

    resp = await client.delete(_remove_url(club.id, member.id))

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


# ========================================================================== #
# Not found
# ========================================================================== #


async def test_remove_from_unknown_club_returns_404(client, db_session):
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
    club = await _seed_club(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, club, member)
    target = await _seed_user(db_session, email="target@example.com", display_name="Target")
    await _seed_member(db_session, club, target)

    # A non-organizer member tries to remove another member.
    resp = await client.delete(
        _remove_url(club.id, target.id),
        headers=_auth_header(member.id),
    )

    assert resp.status_code == 403, resp.text


# ========================================================================== #
# Organizer removing self (409)
# ========================================================================== #


async def test_organizer_removes_self_returns_409_and_still_active(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.delete(
        _remove_url(club.id, organizer.id),
        headers=_auth_header(organizer.id),
    )

    assert resp.status_code == 409, resp.text

    club_id = club.id
    organizer_id = organizer.id
    db_session.expire_all()

    membership = await db_session.scalar(
        select(ClubMember).where(
            ClubMember.club_id == club_id,
            ClubMember.user_id == organizer_id,
        )
    )
    assert membership is not None
    assert membership.removed_at is None


# ========================================================================== #
# Target not an active member (404)
# ========================================================================== #


async def test_remove_non_member_returns_404(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    stranger = await _seed_user(db_session, email="stranger@example.com", display_name="Stranger")

    resp = await client.delete(
        _remove_url(club.id, stranger.id),
        headers=_auth_header(organizer.id),
    )

    assert resp.status_code == 404, resp.text


async def test_remove_already_removed_member_returns_404(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, club, member, removed_at=datetime.now(timezone.utc))

    resp = await client.delete(
        _remove_url(club.id, member.id),
        headers=_auth_header(organizer.id),
    )

    assert resp.status_code == 404, resp.text


# ========================================================================== #
# Happy path — soft delete (204)
# ========================================================================== #


async def test_organizer_removes_active_member_returns_204_and_soft_deletes(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, club, member)

    resp = await client.delete(
        _remove_url(club.id, member.id),
        headers=_auth_header(organizer.id),
    )

    assert resp.status_code == 204, resp.text
    assert resp.content == b""

    club_id = club.id
    member_id = member.id
    db_session.expire_all()

    rows = (
        await db_session.scalars(
            select(ClubMember).where(
                ClubMember.club_id == club_id,
                ClubMember.user_id == member_id,
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].removed_at is not None


# ========================================================================== #
# Integration — removed member loses access
# ========================================================================== #


# ========================================================================== #
# Self-leave (MYS-97)
# ========================================================================== #


async def test_member_can_leave_own_club(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, club, member)

    resp = await client.delete(
        _remove_url(club.id, member.id),
        headers=_auth_header(member.id),
    )

    assert resp.status_code == 204, resp.text

    club_id = club.id
    member_id = member.id
    db_session.expire_all()

    row = await db_session.scalar(
        select(ClubMember).where(
            ClubMember.club_id == club_id,
            ClubMember.user_id == member_id,
        )
    )
    assert row is not None
    assert row.removed_at is not None


async def test_organizer_cannot_self_leave(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.delete(
        _remove_url(club.id, organizer.id),
        headers=_auth_header(organizer.id),
    )

    assert resp.status_code == 409, resp.text
    assert "organizer" in resp.json()["detail"]


async def test_non_member_self_leave_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    stranger = await _seed_user(db_session, email="stranger@example.com", display_name="Stranger")

    resp = await client.delete(
        _remove_url(club.id, stranger.id),
        headers=_auth_header(stranger.id),
    )

    assert resp.status_code == 403, resp.text


async def test_removed_co_organizer_loses_access_to_invites(client, db_session):
    # Invite creation is organizer/co-organizer only (MYS-246), so this needs
    # an admin member to have access to lose in the first place.
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, club, co_organizer, role="admin")

    # Sanity: while active, the co-organizer CAN generate an invite.
    pre = await client.post(_invites_url(club.id), headers=_auth_header(co_organizer.id))
    assert pre.status_code == 201, pre.text

    # Organizer removes the co-organizer.
    removed = await client.delete(
        _remove_url(club.id, co_organizer.id),
        headers=_auth_header(organizer.id),
    )
    assert removed.status_code == 204, removed.text

    # The removed co-organizer can no longer generate invites — the
    # active-admin gate now rejects them.
    post = await client.post(_invites_url(club.id), headers=_auth_header(co_organizer.id))
    assert post.status_code == 403, post.text
