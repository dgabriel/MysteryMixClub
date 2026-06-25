"""Tests for MYS-50: DELETE /api/v1/users/me (account soft-delete).

Right-to-be-forgotten part 1. DELETE /users/me requires auth, blocks while the
caller organizes an active league (409), and otherwise soft-deletes the caller
in one commit: sets deleted_at, tombstones the email to
``deleted+{id}@deleted.invalid``, and invalidates all of the caller's sessions
(204). It does NOT remove submissions/votes/notes/memberships — those wait for
the scheduled hard purge (see test_purge_accounts.py).

Covers: 401 unauthenticated, happy-path soft-delete + persisted state, the old
token being locked out afterward, the active-organizer block, a completed-league
organizer NOT being blocked, and the tombstoned email freeing re-signup.

PKs are captured into locals before any expire_all (project MissingGreenlet
gotcha). See technical-design §5, §6, §10.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.invite import Invite
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.session import Session
from app.models.user import User

ME_URL = "/api/v1/users/me"
REQUEST_URL = "/api/v1/auth/request"
VERIFY_URL = "/api/v1/auth/verify"


# --------------------------------------------------------------------------- #
# Helpers (mirror test_users_me.py / test_authorization_isolation.py factories)
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, **overrides) -> User:
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


async def _seed_session(db_session, user_id: uuid.UUID, **overrides) -> Session:
    """Seed a session row for ``user_id``. invalidated_at defaults to NULL."""
    defaults = {
        "user_id": user_id,
        "refresh_token_hash": "hash-" + uuid.uuid4().hex,
        "device_hint": "TestAgent/1.0",
        "invalidated_at": None,
    }
    defaults.update(overrides)
    session = Session(**defaults)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


async def _seed_league(db_session, organizer_id: uuid.UUID, *, state: str) -> League:
    league = League(
        name="A League",
        organizer_id=organizer_id,
        total_rounds=3,
        votes_per_player=3,
        state=state,
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer_id))
    await db_session.commit()
    await db_session.refresh(league)
    return league


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


_BLOCK_DETAIL = "finish or hand off the leagues you organize before deleting your account"


# --------------------------------------------------------------------------- #
# Error states
# --------------------------------------------------------------------------- #


async def test_delete_unauthenticated_returns_401(client):
    resp = await client.delete(ME_URL)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


async def test_delete_soft_deletes_tombstones_email_and_kills_sessions(client, db_session):
    user = await _seed_user(db_session, email="gone@example.com")
    user_id = user.id
    # Two live sessions plus one already-invalidated session.
    await _seed_session(db_session, user_id)
    await _seed_session(db_session, user_id)
    already = datetime.now(timezone.utc)
    await _seed_session(db_session, user_id, invalidated_at=already)

    resp = await client.delete(ME_URL, headers=_auth_header(user_id))

    assert resp.status_code == 204, resp.text
    assert resp.content == b""

    # Re-query persisted state from the DB.
    db_session.expire_all()
    fresh = await db_session.scalar(select(User).where(User.id == user_id))
    assert fresh is not None
    assert fresh.deleted_at is not None
    assert fresh.email == f"deleted+{user_id}@deleted.invalid"

    sessions = (
        (await db_session.execute(select(Session).where(Session.user_id == user_id)))
        .scalars()
        .all()
    )
    assert len(sessions) == 3
    # Every session is now invalidated (the two live ones got stamped; the
    # pre-invalidated one is still invalidated).
    assert all(s.invalidated_at is not None for s in sessions)


async def test_old_token_rejected_after_delete(client, db_session):
    user = await _seed_user(db_session, email="locked-out@example.com")
    user_id = user.id
    token_header = _auth_header(user_id)

    resp = await client.delete(ME_URL, headers=token_header)
    assert resp.status_code == 204, resp.text

    # The same access token must now be rejected by get_current_user's
    # deleted_at filter — a follow-up GET /users/me returns 401.
    follow_up = await client.get(ME_URL, headers=token_header)
    assert follow_up.status_code == 401, follow_up.text
    assert follow_up.json()["detail"] == "not authenticated"


# --------------------------------------------------------------------------- #
# Organizer block (409) — does not soft-delete
# --------------------------------------------------------------------------- #


async def test_active_league_organizer_blocked_409_and_not_deleted(client, db_session):
    user = await _seed_user(db_session, email="organizer@example.com")
    user_id = user.id
    await _seed_league(db_session, user_id, state="active")

    resp = await client.delete(ME_URL, headers=_auth_header(user_id))

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == _BLOCK_DETAIL

    # The account must NOT be soft-deleted.
    db_session.expire_all()
    fresh = await db_session.scalar(select(User).where(User.id == user_id))
    assert fresh is not None
    assert fresh.deleted_at is None
    assert fresh.email == "organizer@example.com"


async def test_completed_league_organizer_not_blocked_204(client, db_session):
    user = await _seed_user(db_session, email="retiree@example.com")
    user_id = user.id
    await _seed_league(db_session, user_id, state="complete")

    resp = await client.delete(ME_URL, headers=_auth_header(user_id))

    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    fresh = await db_session.scalar(select(User).where(User.id == user_id))
    assert fresh is not None
    assert fresh.deleted_at is not None
    assert fresh.email == f"deleted+{user_id}@deleted.invalid"


# --------------------------------------------------------------------------- #
# Re-signup frees the tombstoned email
# --------------------------------------------------------------------------- #


async def test_resignup_after_delete_creates_new_user_same_email(client, db_session, email_spy):
    # v2 (MYS-127): a deleted account is no longer an existing user, so coming
    # back requires a fresh invite link — which is exactly the realistic path.
    email = "comeback@example.com"
    user = await _seed_user(db_session, email=email)
    deleted_id = user.id

    resp = await client.delete(ME_URL, headers=_auth_header(deleted_id))
    assert resp.status_code == 204, resp.text

    # A fresh shareable invite (organizer + league seeded for it).
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer.id, state="active")
    invite_token = "tok_" + uuid.uuid4().hex
    db_session.add(Invite(league_id=league.id, created_by=organizer.id, token=invite_token))
    await db_session.commit()

    # Email is now tombstoned, freeing the original address. Re-run the magic-link
    # flow for the same email, this time carrying the invite token.
    req = await client.post(REQUEST_URL, json={"email": email, "invite_token": invite_token})
    assert req.status_code == 200, req.text
    _, link = email_spy.calls[-1]
    raw = link.split("token=")[1].split("&")[0]

    verify = await client.get(VERIFY_URL, params={"token": raw, "invite": invite_token})
    assert verify.status_code == 200, verify.text

    # A brand-new, non-deleted user owns the email now.
    db_session.expire_all()
    new_user = await db_session.scalar(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    assert new_user is not None
    assert new_user.id != deleted_id

    # The original (deleted) user still exists, tombstoned.
    old_user = await db_session.scalar(select(User).where(User.id == deleted_id))
    assert old_user is not None
    assert old_user.deleted_at is not None
    assert old_user.email == f"deleted+{deleted_id}@deleted.invalid"
