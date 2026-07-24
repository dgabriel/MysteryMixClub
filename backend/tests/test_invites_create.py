"""Tests for MYS-13 + MYS-126 + MYS-246: POST/DELETE /api/v1/clubs/{id}/invites.

A v2 invite is a single anonymous shareable link with a 48h expiry (MYS-126).
Creation is organizer/co-organizer only (MYS-246) — a plain member can no
longer generate or revoke a club's invite link. Covers auth (401), missing
club (404), non-admin rejection (403), happy-path response shape, the
URL-safe crypto-random token, two calls return different tokens, persistence,
the ~48h expires_at, and organizer-only revoke. See technical-design.md §6
(invites) and §7 (Invites API).
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.invite import Invite
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.user import User

# The exact key set the invite-create response must return.
_INVITE_KEYS = {
    "id",
    "club_id",
    "token",
    "created_by",
    "created_at",
    "expires_at",
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
    """Insert and commit a Club owned by ``organizer``, returning it.

    Also seeds the organizer's active club_members row, mirroring how
    create_club behaves, so the organizer is an active member by default.
    """
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


def _invites_url(club_id) -> str:
    return f"/api/v1/clubs/{club_id}/invites"


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


async def test_unauthenticated_create_invite_returns_401(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.post(_invites_url(club.id))

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


# --------------------------------------------------------------------------- #
# Missing club
# --------------------------------------------------------------------------- #


async def test_create_invite_for_missing_club_returns_404(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.post(_invites_url(uuid.uuid4()), headers=_auth_header(user.id))

    assert resp.status_code == 404, resp.text


# --------------------------------------------------------------------------- #
# Authorization — non-member and non-admin member rejected (MYS-246)
# --------------------------------------------------------------------------- #


async def test_non_member_cannot_create_invite_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    outsider = await _seed_user(db_session, email="outsider@example.com", display_name="Out")

    resp = await client.post(_invites_url(club.id), headers=_auth_header(outsider.id))

    assert resp.status_code == 403, resp.text


async def test_removed_member_cannot_create_invite_returns_403(client, db_session):
    from datetime import datetime, timezone

    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    former = await _seed_user(db_session, email="former@example.com", display_name="Former")
    await _seed_member(db_session, club, former, removed_at=datetime.now(timezone.utc))

    resp = await client.post(_invites_url(club.id), headers=_auth_header(former.id))

    assert resp.status_code == 403, resp.text


# --------------------------------------------------------------------------- #
# Happy path — response shape
# --------------------------------------------------------------------------- #


async def test_organizer_creates_invite_returns_201_and_shape(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.post(_invites_url(club.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert set(data.keys()) == _INVITE_KEYS
    assert data["club_id"] == str(club.id)
    assert data["created_by"] == str(organizer.id)
    # v2 (MYS-126): a shareable link now carries a 48h expiry.
    assert data["expires_at"] is not None
    assert uuid.UUID(data["id"])
    # token is a non-empty, reasonably long URL-safe string.
    assert isinstance(data["token"], str)
    assert len(data["token"]) >= 20


async def test_active_non_admin_member_cannot_create_invite_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, club, member)

    resp = await client.post(_invites_url(club.id), headers=_auth_header(member.id))

    assert resp.status_code == 403, resp.text


async def test_co_organizer_can_create_invite_returns_201(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, club, co_organizer, role="admin")

    resp = await client.post(_invites_url(club.id), headers=_auth_header(co_organizer.id))

    assert resp.status_code == 201, resp.text
    assert resp.json()["created_by"] == str(co_organizer.id)


# --------------------------------------------------------------------------- #
# Token uniqueness — no reuse
# --------------------------------------------------------------------------- #


async def test_two_successive_invites_have_different_tokens(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)
    header = _auth_header(organizer.id)

    first = await client.post(_invites_url(club.id), headers=header)
    second = await client.post(_invites_url(club.id), headers=header)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["token"] != second.json()["token"]


# --------------------------------------------------------------------------- #
# Persistence side effects
# --------------------------------------------------------------------------- #


async def test_create_invite_persists_invites_row(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.post(_invites_url(club.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]

    club_id = club.id
    organizer_id = organizer.id
    db_session.expire_all()

    invites = (await db_session.scalars(select(Invite).where(Invite.token == token))).all()
    assert len(invites) == 1
    invite = invites[0]
    assert invite.club_id == club_id
    assert invite.created_by == organizer_id
    # v2 (MYS-126): persisted with a 48h expiry, not None.
    assert invite.expires_at is not None


# --------------------------------------------------------------------------- #
# 48h expiry (MYS-126)
# --------------------------------------------------------------------------- #


async def test_invite_expires_at_is_about_48h_from_creation(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.post(_invites_url(club.id), headers=_auth_header(organizer.id))
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]

    db_session.expire_all()
    invite = (await db_session.scalars(select(Invite).where(Invite.token == token))).one()
    assert invite.expires_at is not None
    delta = invite.expires_at - invite.created_at
    # ~48h, allowing a little skew between the app clock and the server default.
    assert abs(delta - timedelta(hours=48)) < timedelta(minutes=5), (
        f"expected ~48h between created_at and expires_at, got {delta}"
    )


# --------------------------------------------------------------------------- #
# Revoke — DELETE /clubs/{id}/invites/{invite_id} (organizer-only)
# --------------------------------------------------------------------------- #


def _revoke_url(club_id, invite_id) -> str:
    return f"/api/v1/clubs/{club_id}/invites/{invite_id}"


async def _seed_invite(db_session, club: Club, creator: User, **overrides) -> Invite:
    defaults = {
        "club_id": club.id,
        "created_by": creator.id,
        "token": "tok_" + uuid.uuid4().hex,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=48),
    }
    defaults.update(overrides)
    invite = Invite(**defaults)
    db_session.add(invite)
    await db_session.commit()
    await db_session.refresh(invite)
    return invite


async def test_revoke_invite_returns_204_and_deletes_row(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)
    invite = await _seed_invite(db_session, club, organizer)
    invite_id = invite.id

    resp = await client.delete(_revoke_url(club.id, invite.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 204, resp.text
    assert resp.content == b""

    db_session.expire_all()
    assert await db_session.scalar(select(Invite).where(Invite.id == invite_id)) is None


async def test_revoke_invite_unauthenticated_returns_401(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)
    invite = await _seed_invite(db_session, club, organizer)

    resp = await client.delete(_revoke_url(club.id, invite.id))

    assert resp.status_code == 401, resp.text


async def test_revoke_invite_non_organizer_member_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, club, member)
    invite = await _seed_invite(db_session, club, organizer)

    resp = await client.delete(_revoke_url(club.id, invite.id), headers=_auth_header(member.id))

    assert resp.status_code == 403, resp.text

    # The invite is untouched.
    invite_id = invite.id
    db_session.expire_all()
    assert await db_session.scalar(select(Invite).where(Invite.id == invite_id)) is not None


async def test_revoke_unknown_invite_returns_404(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.delete(
        _revoke_url(club.id, uuid.uuid4()), headers=_auth_header(organizer.id)
    )

    assert resp.status_code == 404, resp.text


async def test_revoke_invite_from_another_club_returns_404(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club_a = await _seed_club(db_session, organizer)
    club_b = await _seed_club(db_session, organizer, name="Other Club")
    invite_b = await _seed_invite(db_session, club_b, organizer)

    resp = await client.delete(
        _revoke_url(club_a.id, invite_b.id), headers=_auth_header(organizer.id)
    )

    assert resp.status_code == 404, resp.text

    # The foreign invite is left intact.
    invite_b_id = invite_b.id
    db_session.expire_all()
    assert await db_session.scalar(select(Invite).where(Invite.id == invite_b_id)) is not None
