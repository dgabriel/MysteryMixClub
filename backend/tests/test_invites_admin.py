"""Tests for MYS-182: admin-generated, league-less signup invites.

Covers:
  POST /api/v1/admin/invites          — platform-admin only, generates a
                                         league-less invite (null league_id)
  GET  /api/v1/invites/{token}        — preview of a platform invite: null
                                         league fields, no membership concept
  POST /api/v1/invites/{token}/accept — rejected (404) for a platform token;
                                         "accept" only makes sense for a league
                                         invite

Signup-time behavior (account created, no league joined) is covered in
test_auth_verify.py, alongside the rest of the invite-gated sign-up suite.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.invite import Invite
from app.models.user import User

ADMIN_EMAIL = "admin@example.com"
CREATE_URL = "/api/v1/admin/invites"

# The exact key set the create response must return — same shape as a league
# invite (InviteResponse), just with a null league_id.
_INVITE_KEYS = {"id", "club_id", "token", "created_by", "created_at", "expires_at"}


@pytest.fixture
def seed_admin_emails() -> str:
    """Make ADMIN_EMAIL a platform admin for the shared ``client`` fixture."""
    return ADMIN_EMAIL


async def _seed_user(db_session, email: str, **overrides) -> User:
    defaults = {"email": email, "display_name": "U"}
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_admin(db_session) -> User:
    return await _seed_user(db_session, ADMIN_EMAIL, display_name="Admin")


async def _seed_platform_invite(db_session, admin: User, **overrides) -> Invite:
    defaults = {
        "club_id": None,
        "created_by": admin.id,
        "token": "tok_" + uuid.uuid4().hex,
        "expires_at": None,
    }
    defaults.update(overrides)
    invite = Invite(**defaults)
    db_session.add(invite)
    await db_session.commit()
    await db_session.refresh(invite)
    return invite


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _preview_url(token: str) -> str:
    return f"/api/v1/invites/{token}"


def _accept_url(token: str) -> str:
    return f"/api/v1/invites/{token}/accept"


# --------------------------------------------------------------------------- #
# POST /admin/invites — creation
# --------------------------------------------------------------------------- #


async def test_create_platform_invite_requires_auth(client, db_session):
    resp = await client.post(CREATE_URL)
    assert resp.status_code == 401


async def test_create_platform_invite_non_admin_forbidden(client, db_session):
    user = await _seed_user(db_session, "u@example.com")
    resp = await client.post(CREATE_URL, headers=_auth(user.id))
    assert resp.status_code == 403


async def test_create_platform_invite_returns_201_and_null_league_id(client, db_session):
    admin = await _seed_admin(db_session)
    resp = await client.post(CREATE_URL, headers=_auth(admin.id))
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert set(data.keys()) == _INVITE_KEYS
    assert data["club_id"] is None
    assert data["created_by"] == str(admin.id)


async def test_create_platform_invite_persists_row_with_null_league_id(client, db_session):
    admin = await _seed_admin(db_session)
    resp = await client.post(CREATE_URL, headers=_auth(admin.id))
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]

    invite = await db_session.scalar(select(Invite).where(Invite.token == token))
    assert invite is not None
    assert invite.league_id is None


async def test_create_platform_invite_expires_at_is_about_48h(client, db_session):
    admin = await _seed_admin(db_session)
    before = datetime.now(timezone.utc)
    resp = await client.post(CREATE_URL, headers=_auth(admin.id))
    assert resp.status_code == 201, resp.text

    expires_at = datetime.fromisoformat(resp.json()["expires_at"])
    delta = expires_at - before
    assert timedelta(hours=47, minutes=55) < delta < timedelta(hours=48, minutes=5)


async def test_two_platform_invites_have_different_tokens(client, db_session):
    admin = await _seed_admin(db_session)
    first = await client.post(CREATE_URL, headers=_auth(admin.id))
    second = await client.post(CREATE_URL, headers=_auth(admin.id))
    assert first.json()["token"] != second.json()["token"]


# --------------------------------------------------------------------------- #
# GET /invites/{token} — preview of a platform invite
# --------------------------------------------------------------------------- #


async def test_preview_platform_invite_returns_null_league_fields(client, db_session):
    admin = await _seed_admin(db_session)
    invite = await _seed_platform_invite(db_session, admin)

    resp = await client.get(_preview_url(invite.token))

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["club_id"] is None
    assert data["club_name"] is None
    assert data["member_count"] is None
    assert data["already_member"] is False


async def test_preview_platform_invite_works_without_auth(client, db_session):
    # Anyone with the link can preview it, same as a league invite.
    admin = await _seed_admin(db_session)
    invite = await _seed_platform_invite(db_session, admin)

    resp = await client.get(_preview_url(invite.token))
    assert resp.status_code == 200


async def test_preview_platform_invite_expired_returns_410(client, db_session):
    admin = await _seed_admin(db_session)
    invite = await _seed_platform_invite(
        db_session, admin, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
    )

    resp = await client.get(_preview_url(invite.token))
    assert resp.status_code == 410, resp.text


async def test_preview_platform_invite_expired_as_authenticated_visitor_still_410(
    client, db_session
):
    # MYS-181's already-member bypass doesn't apply — there's no league to be
    # a member of, so an expired platform invite always 410s.
    admin = await _seed_admin(db_session)
    visitor = await _seed_user(db_session, "visitor@example.com")
    invite = await _seed_platform_invite(
        db_session, admin, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
    )

    resp = await client.get(_preview_url(invite.token), headers=_auth(visitor.id))
    assert resp.status_code == 410, resp.text


async def test_preview_platform_invite_already_used_returns_410(client, db_session):
    # Single-use (MYS-182 follow-up): a used_at stamp reads the same as
    # expired — same status/copy, no separate frontend state — for anyone
    # other than the visitor who used it (see the self-bypass tests below).
    admin = await _seed_admin(db_session)
    invite = await _seed_platform_invite(db_session, admin, used_at=datetime.now(timezone.utc))

    resp = await client.get(_preview_url(invite.token))
    assert resp.status_code == 410, resp.text


async def test_preview_platform_invite_used_by_a_different_authenticated_user_still_410(
    client, db_session
):
    admin = await _seed_admin(db_session)
    user = await _seed_user(db_session, "used-it@example.com")
    someone_else = await _seed_user(db_session, "someone-else@example.com")
    invite = await _seed_platform_invite(
        db_session, admin, used_at=datetime.now(timezone.utc), used_by_user_id=user.id
    )

    resp = await client.get(_preview_url(invite.token), headers=_auth(someone_else.id))
    assert resp.status_code == 410, resp.text


async def test_preview_platform_invite_used_by_self_passes_through(client, db_session):
    """MYS-183 fix: onboarding stashes a pending-invite path that redirects
    back to this same URL once it's done. The visitor who consumed the
    invite during signup must not get bounced to an "expired" error for
    revisiting the link they just used."""
    admin = await _seed_admin(db_session)
    user = await _seed_user(db_session, "used-it@example.com")
    invite = await _seed_platform_invite(
        db_session, admin, used_at=datetime.now(timezone.utc), used_by_user_id=user.id
    )

    resp = await client.get(_preview_url(invite.token), headers=_auth(user.id))

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["club_id"] is None
    assert data["already_member"] is False


# --------------------------------------------------------------------------- #
# POST /invites/{token}/accept — rejected for a platform invite
# --------------------------------------------------------------------------- #


async def test_accept_platform_invite_returns_404(client, db_session):
    # "Accept" only makes sense for a league invite; a platform token isn't a
    # league to join. The frontend never calls this for a league-less token —
    # this guards a stray/direct call.
    admin = await _seed_admin(db_session)
    visitor = await _seed_user(db_session, "visitor@example.com")
    invite = await _seed_platform_invite(db_session, admin)

    resp = await client.post(_accept_url(invite.token), headers=_auth(visitor.id))
    assert resp.status_code == 404, resp.text
