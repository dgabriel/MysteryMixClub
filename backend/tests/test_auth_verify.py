"""Tests for MYS-7 + MYS-127: GET /api/v1/auth/verify (magic-link verification).

Covers happy path (token -> JWT + refresh cookie + session row), edge cases
(existing-user re-login, expired token), error states (token reuse, garbage
token, missing param), and the v2 invite-gated sign-up + cap model (MYS-127):

- A NEW account can only be created when a valid unexpired invite token rode
  through on the link's &invite= (else 403 invite-required), and creation is
  blocked once the user cap is reached (403 at-capacity).
- An EXISTING user signs in with no invite at all.
- A valid invite joins the (new or existing) user to that league, idempotently.

See technical-design.md §5, §6.

PKs are captured into locals before any expire_all (project MissingGreenlet
gotcha).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import func, select

from app.auth.tokens import hash_token
from app.config import get_settings
from app.models.invite import Invite
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.magic_link_token import MagicLinkToken
from app.models.session import Session
from app.models.user import User

REQUEST_URL = "/api/v1/auth/request"
VERIFY_URL = "/api/v1/auth/verify"
_JWT_ALGORITHM = "HS256"

_INVITE_REQUIRED_MESSAGE = "you need an invite to create an account"
_AT_CAPACITY_MESSAGE = "MysteryMixClub is at capacity right now"


# --------------------------------------------------------------------------- #
# Helpers
#
# v2 (MYS-127): /auth/request only mails a link to an existing user or via a
# valid invite token, and a NEW account at /auth/verify requires that invite to
# ride along on &invite=. Helpers seed the precondition (existing user, or a
# league + shareable invite) and run the real flow.
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, **overrides) -> User:
    defaults = {"email": email, "display_name": ""}
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_league_with_invite(db_session, *, expires_at: datetime | None = None) -> Invite:
    """Seed an organizer + active league + shareable invite; return the Invite."""
    organizer = User(email="org@example.com", display_name="Org")
    db_session.add(organizer)
    await db_session.flush()
    league = League(
        name="Invited League",
        organizer_id=organizer.id,
        total_rounds=3,
        votes_per_player=3,
        state="active",
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    invite = Invite(
        league_id=league.id,
        created_by=organizer.id,
        token="tok_" + uuid.uuid4().hex,
        expires_at=expires_at,
    )
    db_session.add(invite)
    await db_session.commit()
    await db_session.refresh(invite)
    return invite


async def _seed_platform_invite(db_session, *, expires_at: datetime | None = None) -> Invite:
    """Seed an admin-generated, league-less invite (MYS-182): grants signup
    only, no league attachment."""
    admin = User(email="admin@example.com", display_name="Admin")
    db_session.add(admin)
    await db_session.flush()
    invite = Invite(
        league_id=None,
        created_by=admin.id,
        token="tok_" + uuid.uuid4().hex,
        expires_at=expires_at,
    )
    db_session.add(invite)
    await db_session.commit()
    await db_session.refresh(invite)
    return invite


async def _request_link(client, email_spy, email: str, invite_token: str | None = None) -> str:
    """Request a magic link and return the raw token from the email link."""
    body: dict[str, str] = {"email": email}
    if invite_token is not None:
        body["invite_token"] = invite_token
    resp = await client.post(REQUEST_URL, json=body)
    assert resp.status_code == 200, f"request -> {resp.status_code}: {resp.text}"
    _, link = email_spy.calls[-1]
    return link.split("token=")[1].split("&")[0]


async def _count(db_session, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for attr, value in filters.items():
        stmt = stmt.where(getattr(model, attr) == value)
    return await db_session.scalar(stmt)


async def _active_member_count(db_session, league_id, user_id) -> int:
    rows = (
        await db_session.scalars(
            select(LeagueMember).where(
                LeagueMember.league_id == league_id,
                LeagueMember.user_id == user_id,
                LeagueMember.removed_at.is_(None),
            )
        )
    ).all()
    return len(rows)


# --------------------------------------------------------------------------- #
# Happy path — existing user signs in (no invite needed)
# --------------------------------------------------------------------------- #


async def test_verify_returns_200_with_bearer_token(client, email_spy, db_session):
    await _seed_user(db_session, "alice@example.com")
    raw = await _request_link(client, email_spy, "alice@example.com")

    resp = await client.get(VERIFY_URL, params={"token": raw})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"access_token", "token_type"}
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]


async def test_jwt_decodes_with_correct_claims_and_60_min_ttl(client, email_spy, db_session):
    settings = get_settings()
    user = await _seed_user(db_session, "alice@example.com")
    user_id = user.id
    raw = await _request_link(client, email_spy, "alice@example.com")

    resp = await client.get(VERIFY_URL, params={"token": raw})
    access_token = resp.json()["access_token"]

    claims = jwt.decode(access_token, settings.secret_key, algorithms=[_JWT_ALGORITHM])
    assert claims["sub"] == str(user_id)
    assert claims["exp"] - claims["iat"] == 3600


async def test_session_row_stores_refresh_hash_not_raw_and_device_hint(
    client, email_spy, db_session
):
    await _seed_user(db_session, "alice@example.com")
    raw = await _request_link(client, email_spy, "alice@example.com")

    resp = await client.get(
        VERIFY_URL,
        params={"token": raw},
        headers={"User-Agent": "MMCTestAgent/1.0"},
    )

    refresh_cookie = resp.cookies.get("refresh_token")
    assert refresh_cookie, "refresh_token cookie not set"

    session_row = (await db_session.execute(select(Session))).scalar_one()
    assert session_row.refresh_token_hash != refresh_cookie
    assert session_row.refresh_token_hash == hash_token(refresh_cookie)
    assert session_row.device_hint == "MMCTestAgent/1.0"


async def test_refresh_cookie_attributes(client, email_spy, db_session):
    await _seed_user(db_session, "alice@example.com")
    raw = await _request_link(client, email_spy, "alice@example.com")

    resp = await client.get(VERIFY_URL, params={"token": raw})

    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    lowered = set_cookie.lower()
    assert "httponly" in lowered, set_cookie
    # Lax (not Strict) so the session survives an OAuth-provider return (MYS-91).
    assert "samesite=lax" in lowered, set_cookie
    assert "path=/api/v1/auth" in lowered, set_cookie
    assert "max-age=2592000" in lowered, set_cookie
    # Development env: cookie must NOT carry the Secure attribute.
    assert "secure" not in lowered, set_cookie


async def test_magic_link_token_deleted_after_successful_verify(client, email_spy, db_session):
    await _seed_user(db_session, "alice@example.com")
    raw = await _request_link(client, email_spy, "alice@example.com")
    assert await _count(db_session, MagicLinkToken) == 1

    resp = await client.get(VERIFY_URL, params={"token": raw})
    assert resp.status_code == 200

    # Single-use: the row is hard-deleted on a successful verify.
    assert await _count(db_session, MagicLinkToken) == 0


# --------------------------------------------------------------------------- #
# Happy path — new account creation requires a valid invite (MYS-127)
# --------------------------------------------------------------------------- #


async def test_first_login_with_invite_creates_user_with_empty_name_and_vibe_false(
    client, email_spy, db_session
):
    invite = await _seed_league_with_invite(db_session)
    token = invite.token

    raw = await _request_link(client, email_spy, "newbie@example.com", invite_token=token)
    resp = await client.get(VERIFY_URL, params={"token": raw, "invite": token})
    assert resp.status_code == 200, resp.text

    new_user = await db_session.scalar(select(User).where(User.email == "newbie@example.com"))
    assert new_user is not None
    assert new_user.display_name == ""


async def test_first_login_with_invite_joins_the_league(client, email_spy, db_session):
    invite = await _seed_league_with_invite(db_session)
    token = invite.token
    league_id = invite.league_id

    raw = await _request_link(client, email_spy, "newbie@example.com", invite_token=token)
    resp = await client.get(VERIFY_URL, params={"token": raw, "invite": token})
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    new_user = await db_session.scalar(select(User).where(User.email == "newbie@example.com"))
    assert new_user is not None
    assert await _active_member_count(db_session, league_id, new_user.id) == 1


async def test_first_login_with_platform_invite_creates_account_without_joining_any_league(
    client, email_spy, db_session
):
    # MYS-182: a platform (league-less) invite grants signup only — the new
    # account is created but joined to nothing, unlike a league invite.
    invite = await _seed_platform_invite(db_session)
    token = invite.token

    raw = await _request_link(client, email_spy, "newbie@example.com", invite_token=token)
    resp = await client.get(VERIFY_URL, params={"token": raw, "invite": token})
    assert resp.status_code == 200, resp.text

    new_user = await db_session.scalar(select(User).where(User.email == "newbie@example.com"))
    assert new_user is not None
    assert new_user.display_name == ""
    assert await _count(db_session, LeagueMember, user_id=new_user.id) == 0


async def test_platform_invite_is_stamped_used_after_first_signup(client, email_spy, db_session):
    # Single-use (MYS-182 follow-up): the invite row records when it was
    # consumed.
    invite = await _seed_platform_invite(db_session)
    token = invite.token
    invite_id = invite.id

    raw = await _request_link(client, email_spy, "newbie@example.com", invite_token=token)
    resp = await client.get(VERIFY_URL, params={"token": raw, "invite": token})
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    used = await db_session.scalar(select(Invite).where(Invite.id == invite_id))
    assert used is not None
    assert used.used_at is not None


async def test_second_new_account_with_same_platform_invite_returns_403(
    client, email_spy, db_session
):
    # Single-use (MYS-182 follow-up): once a platform invite has gated one new
    # account, a second brand-new email can't use the same token.
    invite = await _seed_platform_invite(db_session)
    token = invite.token

    raw1 = await _request_link(client, email_spy, "first@example.com", invite_token=token)
    resp1 = await client.get(VERIFY_URL, params={"token": raw1, "invite": token})
    assert resp1.status_code == 200, resp1.text

    # /auth/request for a second new email with the now-used token: the
    # invite no longer validates, so this is the same neutral no-send as no
    # invite at all — no dev_token means no email would be sent.
    req2 = await client.post(
        REQUEST_URL, json={"email": "second@example.com", "invite_token": token}
    )
    assert req2.status_code == 200
    assert req2.json().get("dev_token") is None

    # Even a token minted before the first signup consumed it (e.g. a raced
    # magic-link click) is rejected at verify time, since the invite is
    # re-validated there.
    db_session.add(
        MagicLinkToken(
            email="second@example.com",
            token_hash=hash_token("second-raw-token"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            used=False,
        )
    )
    await db_session.commit()
    resp2 = await client.get(VERIFY_URL, params={"token": "second-raw-token", "invite": token})
    assert resp2.status_code == 403, resp2.text
    assert resp2.json()["detail"] == _INVITE_REQUIRED_MESSAGE

    second_user = await db_session.scalar(select(User).where(User.email == "second@example.com"))
    assert second_user is None


async def test_league_invite_stays_multi_use_after_a_new_signup(client, email_spy, db_session):
    # The single-use change is scoped to platform invites only — a league
    # invite must keep working for every subsequent person (MYS-182 follow-up
    # explicitly does not touch this path).
    invite = await _seed_league_with_invite(db_session)
    token = invite.token
    league_id = invite.league_id
    invite_id = invite.id

    raw1 = await _request_link(client, email_spy, "first@example.com", invite_token=token)
    resp1 = await client.get(VERIFY_URL, params={"token": raw1, "invite": token})
    assert resp1.status_code == 200, resp1.text

    raw2 = await _request_link(client, email_spy, "second@example.com", invite_token=token)
    resp2 = await client.get(VERIFY_URL, params={"token": raw2, "invite": token})
    assert resp2.status_code == 200, resp2.text

    db_session.expire_all()
    second_user = await db_session.scalar(select(User).where(User.email == "second@example.com"))
    assert second_user is not None
    assert await _active_member_count(db_session, league_id, second_user.id) == 1

    invite_row = await db_session.scalar(select(Invite).where(Invite.id == invite_id))
    assert invite_row is not None
    assert invite_row.used_at is None


async def test_new_account_without_invite_param_returns_403(client, db_session):
    # A magic-link token exists for a never-seen email but NO invite rides along
    # (e.g. someone replayed a bare verify URL). New-account creation is refused.
    raw = "loose-token-value"
    db_session.add(
        MagicLinkToken(
            email="loose@example.com",
            token_hash=hash_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            used=False,
        )
    )
    await db_session.commit()

    resp = await client.get(VERIFY_URL, params={"token": raw})

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == _INVITE_REQUIRED_MESSAGE
    # No account created; the single-use token is still consumed.
    db_session.expire_all()
    assert await _count(db_session, User, email="loose@example.com") == 0
    assert await _count(db_session, MagicLinkToken) == 0


async def test_new_account_with_expired_invite_param_returns_403(client, db_session):
    invite = await _seed_league_with_invite(
        db_session, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    token = invite.token
    # Seed the magic-link token directly so we control the (expired) invite param.
    raw = "raw-token-value"
    db_session.add(
        MagicLinkToken(
            email="late@example.com",
            token_hash=hash_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            used=False,
        )
    )
    await db_session.commit()

    resp = await client.get(VERIFY_URL, params={"token": raw, "invite": token})

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == _INVITE_REQUIRED_MESSAGE
    db_session.expire_all()
    assert await _count(db_session, User, email="late@example.com") == 0


# --------------------------------------------------------------------------- #
# Cap (MYS-127): new sign-ups blocked at max_users; existing users unaffected
# --------------------------------------------------------------------------- #


class TestUserCap:
    # Cap of 1 — the seeded organizer already fills it, so a new sign-up is blocked.
    @pytest.fixture
    def max_users(self) -> int:
        return 1

    async def test_new_signup_blocked_at_capacity_returns_403(self, client, email_spy, db_session):
        invite = await _seed_league_with_invite(db_session)  # organizer = 1 user
        token = invite.token

        raw = await _request_link(client, email_spy, "overflow@example.com", invite_token=token)
        resp = await client.get(VERIFY_URL, params={"token": raw, "invite": token})

        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == _AT_CAPACITY_MESSAGE
        db_session.expire_all()
        assert await _count(db_session, User, email="overflow@example.com") == 0


class TestExistingUserUnaffectedByCap:
    @pytest.fixture
    def max_users(self) -> int:
        return 1

    async def test_existing_user_can_sign_in_even_at_capacity(self, client, email_spy, db_session):
        # The single allowed slot is taken by this existing user; they still log in.
        await _seed_user(db_session, "resident@example.com")

        raw = await _request_link(client, email_spy, "resident@example.com")
        resp = await client.get(VERIFY_URL, params={"token": raw})

        assert resp.status_code == 200, resp.text


# --------------------------------------------------------------------------- #
# Invite param joins an EXISTING user too, idempotently
# --------------------------------------------------------------------------- #


async def test_existing_user_following_invite_joins_league(client, email_spy, db_session):
    invite = await _seed_league_with_invite(db_session)
    token = invite.token
    league_id = invite.league_id
    user = await _seed_user(db_session, "follower@example.com")
    user_id = user.id

    raw = await _request_link(client, email_spy, "follower@example.com", invite_token=token)
    resp = await client.get(VERIFY_URL, params={"token": raw, "invite": token})
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    assert await _active_member_count(db_session, league_id, user_id) == 1


async def test_invite_join_is_idempotent_on_second_login(client, email_spy, db_session):
    invite = await _seed_league_with_invite(db_session)
    token = invite.token
    league_id = invite.league_id

    raw1 = await _request_link(client, email_spy, "newbie@example.com", invite_token=token)
    r1 = await client.get(VERIFY_URL, params={"token": raw1, "invite": token})
    assert r1.status_code == 200, r1.text

    raw2 = await _request_link(client, email_spy, "newbie@example.com", invite_token=token)
    r2 = await client.get(VERIFY_URL, params={"token": raw2, "invite": token})
    assert r2.status_code == 200, r2.text

    db_session.expire_all()
    user = await db_session.scalar(select(User).where(User.email == "newbie@example.com"))
    assert user is not None
    user_id = user.id
    # Exactly one membership row total — no duplicate insert on the second login.
    all_rows = (
        await db_session.scalars(
            select(LeagueMember).where(
                LeagueMember.league_id == league_id,
                LeagueMember.user_id == user_id,
            )
        )
    ).all()
    assert len(all_rows) == 1
    assert all_rows[0].removed_at is None


async def test_invite_reactivates_removed_membership(client, email_spy, db_session):
    invite = await _seed_league_with_invite(db_session)
    token = invite.token
    league_id = invite.league_id

    # The user existed, joined, and was removed previously.
    user = await _seed_user(db_session, "returning@example.com")
    user_id = user.id
    removed = LeagueMember(
        league_id=league_id, user_id=user_id, removed_at=datetime.now(timezone.utc)
    )
    db_session.add(removed)
    await db_session.commit()
    await db_session.refresh(removed)
    original_member_id = removed.id

    raw = await _request_link(client, email_spy, "returning@example.com", invite_token=token)
    resp = await client.get(VERIFY_URL, params={"token": raw, "invite": token})
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    rows = (
        await db_session.scalars(
            select(LeagueMember).where(
                LeagueMember.league_id == league_id,
                LeagueMember.user_id == user_id,
            )
        )
    ).all()
    # Reactivated in place — one row, the original, now active again.
    assert len(rows) == 1
    assert rows[0].id == original_member_id
    assert rows[0].removed_at is None


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #


async def test_second_login_same_email_one_user_two_sessions(client, email_spy, db_session):
    email = "repeat@example.com"
    await _seed_user(db_session, email)

    raw1 = await _request_link(client, email_spy, email)
    r1 = await client.get(VERIFY_URL, params={"token": raw1})
    assert r1.status_code == 200, r1.text

    raw2 = await _request_link(client, email_spy, email)
    r2 = await client.get(VERIFY_URL, params={"token": raw2})
    assert r2.status_code == 200, r2.text

    assert await _count(db_session, User, email=email) == 1
    assert await _count(db_session, Session) == 2


async def test_expired_token_returns_401_and_is_deleted(client, db_session):
    # Insert an already-expired token directly; raw token is what the client sends.
    raw = "expired-raw-token-value"
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.add(
        MagicLinkToken(
            email="expired@example.com",
            token_hash=hash_token(raw),
            expires_at=past,
            used=False,
        )
    )
    await db_session.commit()
    assert await _count(db_session, MagicLinkToken) == 1

    resp = await client.get(VERIFY_URL, params={"token": raw})
    assert resp.status_code == 401, resp.text

    # Single-use even on the expired path: the row is hard-deleted.
    db_session.expire_all()
    assert await _count(db_session, MagicLinkToken) == 0
    assert await _count(db_session, User) == 0
    assert await _count(db_session, Session) == 0


# --------------------------------------------------------------------------- #
# Error states
# --------------------------------------------------------------------------- #


async def test_reusing_token_second_call_401_no_extra_session(client, email_spy, db_session):
    await _seed_user(db_session, "alice@example.com")
    raw = await _request_link(client, email_spy, "alice@example.com")

    first = await client.get(VERIFY_URL, params={"token": raw})
    assert first.status_code == 200, first.text
    assert await _count(db_session, Session) == 1

    second = await client.get(VERIFY_URL, params={"token": raw})
    assert second.status_code == 401, second.text

    db_session.expire_all()
    assert await _count(db_session, Session) == 1


async def test_garbage_token_returns_401_no_user_or_session(client, db_session):
    resp = await client.get(VERIFY_URL, params={"token": "this-token-does-not-exist"})

    assert resp.status_code == 401, resp.text
    assert await _count(db_session, User) == 0
    assert await _count(db_session, Session) == 0


async def test_missing_token_param_returns_422(client, db_session):
    resp = await client.get(VERIFY_URL)

    assert resp.status_code == 422, resp.text
    assert await _count(db_session, User) == 0
    assert await _count(db_session, Session) == 0
