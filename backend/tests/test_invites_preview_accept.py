"""Tests for MYS-13: invite preview and accept.

Covers:
  GET  /api/v1/invites/{token}         — unauthenticated league preview
  POST /api/v1/invites/{token}/accept  — authenticated join

TDD-first: written before the Invite model and the invite endpoints exist, so
they are expected to FAIL (red) until the developer implements them. See
technical-design.md §6 (invites, league_members) and §7 (Invites API).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.invite import Invite
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.user import User

# The exact key set the preview response must return.
_PREVIEW_KEYS = {"league_name", "member_count"}

# The full league object key set, matching POST /leagues.
_LEAGUE_KEYS = {
    "id",
    "name",
    "description",
    "organizer_id",
    "total_rounds",
    "votes_per_player",
    "current_round",
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
        "default_vibe_mode": False,
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


async def _seed_invite(db_session, league: League, creator: User, **overrides) -> Invite:
    """Insert and commit an Invite row, returning it."""
    defaults = {
        "league_id": league.id,
        "created_by": creator.id,
        "token": "tok_" + uuid.uuid4().hex,
        "expires_at": None,
    }
    defaults.update(overrides)
    invite = Invite(**defaults)
    db_session.add(invite)
    await db_session.commit()
    await db_session.refresh(invite)
    return invite


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _preview_url(token: str) -> str:
    return f"/api/v1/invites/{token}"


def _accept_url(token: str) -> str:
    return f"/api/v1/invites/{token}/accept"


async def _active_membership_count(db_session, league_id, user_id) -> int:
    rows = (
        await db_session.scalars(
            select(LeagueMember).where(
                LeagueMember.league_id == league_id,
                LeagueMember.user_id == user_id,
            )
        )
    ).all()
    return len(rows)


# ========================================================================== #
# Endpoint B — GET /api/v1/invites/{token}  (unauthenticated preview)
# ========================================================================== #


async def test_preview_unknown_token_returns_404(client, db_session):
    resp = await client.get(_preview_url("garbage-token-does-not-exist"))

    assert resp.status_code == 404, resp.text


async def test_preview_works_without_auth_header_returns_200_and_shape(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)
    invite = await _seed_invite(db_session, league, organizer)

    # No Authorization header at all.
    resp = await client.get(_preview_url(invite.token))

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) == _PREVIEW_KEYS
    assert data["league_name"] == league.name


async def test_preview_member_count_counts_only_active_members(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)  # organizer = 1 active member
    # Two more active members -> 3 active total.
    m1 = await _seed_user(db_session, email="m1@example.com", display_name="M1")
    m2 = await _seed_user(db_session, email="m2@example.com", display_name="M2")
    await _seed_member(db_session, league, m1)
    await _seed_member(db_session, league, m2)
    # One removed member that must NOT be counted.
    removed = await _seed_user(db_session, email="rem@example.com", display_name="Rem")
    await _seed_member(db_session, league, removed, removed_at=datetime.now(timezone.utc))

    invite = await _seed_invite(db_session, league, organizer)

    resp = await client.get(_preview_url(invite.token))

    assert resp.status_code == 200, resp.text
    assert resp.json()["member_count"] == 3


# ========================================================================== #
# Endpoint C — POST /api/v1/invites/{token}/accept  (authenticated join)
# ========================================================================== #


async def test_unauthenticated_accept_returns_401(client, db_session):
    organizer = await _seed_user(db_session)
    league = await _seed_league(db_session, organizer)
    invite = await _seed_invite(db_session, league, organizer)

    resp = await client.post(_accept_url(invite.token))

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


async def test_accept_unknown_token_returns_404(client, db_session):
    joiner = await _seed_user(db_session)

    resp = await client.post(
        _accept_url("garbage-token-does-not-exist"), headers=_auth_header(joiner.id)
    )

    assert resp.status_code == 404, resp.text


async def test_new_user_accept_returns_200_and_full_league_shape(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    invite = await _seed_invite(db_session, league, organizer)
    joiner = await _seed_user(db_session, email="join@example.com", display_name="Joiner")

    resp = await client.post(_accept_url(invite.token), headers=_auth_header(joiner.id))

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) == _LEAGUE_KEYS
    assert data["id"] == str(league.id)
    assert data["name"] == league.name


async def test_new_user_accept_persists_active_membership(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    invite = await _seed_invite(db_session, league, organizer)
    joiner = await _seed_user(db_session, email="join@example.com", display_name="Joiner")

    resp = await client.post(_accept_url(invite.token), headers=_auth_header(joiner.id))

    assert resp.status_code == 200, resp.text

    league_id = league.id
    joiner_id = joiner.id
    db_session.expire_all()

    members = (
        await db_session.scalars(
            select(LeagueMember).where(
                LeagueMember.league_id == league_id,
                LeagueMember.user_id == joiner_id,
            )
        )
    ).all()
    assert len(members) == 1
    assert members[0].removed_at is None


async def test_duplicate_active_membership_accept_returns_409_and_no_new_row(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    invite = await _seed_invite(db_session, league, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, league, member)  # already active

    resp = await client.post(_accept_url(invite.token), headers=_auth_header(member.id))

    assert resp.status_code == 409, resp.text

    league_id = league.id
    member_id = member.id
    db_session.expire_all()

    count = await _active_membership_count(db_session, league_id, member_id)
    assert count == 1


async def test_reactivation_accept_returns_200_and_reuses_same_row(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    invite = await _seed_invite(db_session, league, organizer)
    returning = await _seed_user(db_session, email="back@example.com", display_name="Back")
    removed = await _seed_member(
        db_session, league, returning, removed_at=datetime.now(timezone.utc)
    )
    original_member_id = removed.id

    resp = await client.post(_accept_url(invite.token), headers=_auth_header(returning.id))

    assert resp.status_code == 200, resp.text

    league_id = league.id
    returning_id = returning.id
    db_session.expire_all()

    members = (
        await db_session.scalars(
            select(LeagueMember).where(
                LeagueMember.league_id == league_id,
                LeagueMember.user_id == returning_id,
            )
        )
    ).all()
    # Exactly one row — the original, reactivated, not a second insert.
    assert len(members) == 1
    assert members[0].id == original_member_id
    assert members[0].removed_at is None
