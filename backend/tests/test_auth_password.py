"""Tests for MysteryMixClub-ali8.1 (ADR 0007): password auth.

Covers POST /auth/login, POST /auth/register (invite-gated password sign-up),
and the POST /auth/forgot-password -> POST /auth/reset-password flow.

The load-bearing property throughout is that magic link is untouched: a
magic-link sign-up still creates an account with no password, and an account
with no password simply can't sign in with one.

PKs are captured into locals before any expire_all (project MissingGreenlet
gotcha).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.auth.passwords import hash_password
from app.auth.tokens import hash_token
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.invite import Invite
from app.models.login_attempt import LoginAttempt
from app.models.password_reset_token import PasswordResetToken
from app.models.session import Session
from app.models.user import User

REQUEST_URL = "/api/v1/auth/request"
VERIFY_URL = "/api/v1/auth/verify"
LOGIN_URL = "/api/v1/auth/login"
REGISTER_URL = "/api/v1/auth/register"
FORGOT_URL = "/api/v1/auth/forgot-password"
RESET_URL = "/api/v1/auth/reset-password"
REFRESH_URL = "/api/v1/auth/refresh"

PASSWORD = "correct horse battery"
NEW_PASSWORD = "a whole new stapler"

_INVALID_CREDENTIALS = "invalid email or password"
_INVALID_LINK = "invalid or expired link"
_INVITE_REQUIRED = "you need an invite to create an account"
_RESET_NEUTRAL = "If that email has a password set, a reset link is on its way."


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, *, password: str | None = None, **overrides) -> User:
    user = User(
        email=email,
        display_name="",
        password_hash=hash_password(password) if password is not None else None,
        **overrides,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_club_invite(db_session, *, organizer_email: str = "org@example.com") -> str:
    """Seed an organizer + active club + shareable club invite; return its token."""
    organizer = User(email=organizer_email, display_name="Org")
    db_session.add(organizer)
    await db_session.flush()
    club = Club(
        name="Invited Club",
        organizer_id=organizer.id,
        total_mixes=3,
        votes_per_player=3,
        state="active",
    )
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    token = "tok_" + uuid.uuid4().hex
    db_session.add(Invite(club_id=club.id, created_by=organizer.id, token=token))
    await db_session.commit()
    return token


async def _seed_platform_invite(db_session, *, email: str | None = None) -> str:
    """Seed a club-less (platform) invite, optionally email-locked (MYS-215)."""
    admin = User(email="admin@example.com", display_name="Admin")
    db_session.add(admin)
    await db_session.flush()
    token = "tok_" + uuid.uuid4().hex
    db_session.add(Invite(club_id=None, created_by=admin.id, token=token, email=email))
    await db_session.commit()
    return token


async def _attempt_count(db_session, email: str) -> int:
    return await db_session.scalar(
        select(func.count()).select_from(LoginAttempt).where(LoginAttempt.email == email)
    )


async def _reset_token_count(db_session, email: str | None = None) -> int:
    stmt = select(func.count()).select_from(PasswordResetToken)
    if email is not None:
        stmt = stmt.where(PasswordResetToken.email == email)
    return await db_session.scalar(stmt)


async def _forgot_and_get_token(client, db_session, email: str) -> str:
    resp = await client.post(FORGOT_URL, json={"email": email})
    assert resp.status_code == 200, resp.text
    token = resp.json()["dev_token"]
    assert token
    return token


# --------------------------------------------------------------------------- #
# POST /auth/login — happy path
# --------------------------------------------------------------------------- #


async def test_login_returns_access_token_and_refresh_cookie(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    resp = await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": PASSWORD})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert resp.cookies.get("refresh_token")


async def test_login_creates_a_session_row_matching_the_cookie(client, db_session):
    user = await _seed_user(db_session, "pw@example.com", password=PASSWORD)
    user_id = user.id

    resp = await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": PASSWORD})

    raw_refresh = resp.cookies["refresh_token"]
    session = await db_session.scalar(
        select(Session).where(Session.refresh_token_hash == hash_token(raw_refresh))
    )
    assert session is not None
    assert session.user_id == user_id
    assert session.invalidated_at is None


async def test_login_session_works_for_refresh(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": PASSWORD})
    # The client's cookie jar retains the refresh cookie (path /api/v1/auth).
    refreshed = await client.post(REFRESH_URL)

    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["access_token"]


async def test_login_email_is_case_insensitive(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    resp = await client.post(LOGIN_URL, json={"email": "PW@Example.COM", "password": PASSWORD})

    assert resp.status_code == 200, resp.text


async def test_successful_login_records_no_attempt_row(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": PASSWORD})

    assert await _attempt_count(db_session, "pw@example.com") == 0


async def test_successful_login_clears_earlier_failures(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    for _ in range(3):
        await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": "wrong"})
    assert await _attempt_count(db_session, "pw@example.com") == 3

    ok = await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": PASSWORD})

    assert ok.status_code == 200, ok.text
    assert await _attempt_count(db_session, "pw@example.com") == 0


# --------------------------------------------------------------------------- #
# POST /auth/login — failure modes are indistinguishable
# --------------------------------------------------------------------------- #


async def test_wrong_password_returns_generic_401(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    resp = await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": "nope"})

    assert resp.status_code == 401
    assert resp.json()["detail"] == _INVALID_CREDENTIALS
    assert "refresh_token" not in resp.cookies


async def test_account_without_password_returns_generic_401(client, db_session):
    # A magic-link-only account cannot sign in with a password, and the refusal
    # is indistinguishable from a wrong password.
    await _seed_user(db_session, "magiconly@example.com")

    resp = await client.post(LOGIN_URL, json={"email": "magiconly@example.com", "password": "any"})

    assert resp.status_code == 401
    assert resp.json()["detail"] == _INVALID_CREDENTIALS


async def test_unknown_email_returns_generic_401(client, db_session):
    resp = await client.post(LOGIN_URL, json={"email": "nobody@example.com", "password": "any"})

    assert resp.status_code == 401
    assert resp.json()["detail"] == _INVALID_CREDENTIALS


async def test_soft_deleted_account_cannot_log_in(client, db_session):
    await _seed_user(
        db_session,
        "ghost@example.com",
        password=PASSWORD,
        deleted_at=datetime.now(timezone.utc),
    )

    resp = await client.post(LOGIN_URL, json={"email": "ghost@example.com", "password": PASSWORD})

    assert resp.status_code == 401
    assert resp.json()["detail"] == _INVALID_CREDENTIALS


async def test_no_session_row_created_on_failed_login(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": "nope"})

    assert await db_session.scalar(select(func.count()).select_from(Session)) == 0


async def test_missing_password_field_returns_422(client, db_session):
    resp = await client.post(LOGIN_URL, json={"email": "pw@example.com"})

    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# POST /auth/login — brute-force rate limiting
# --------------------------------------------------------------------------- #


async def test_rate_limit_boundary_ten_failures_then_429(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    for i in range(10):
        r = await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": "nope"})
        assert r.status_code == 401, f"attempt {i + 1} -> {r.status_code}"

    blocked = await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": "nope"})

    assert blocked.status_code == 429
    # The blocked request must not add an 11th row.
    assert await _attempt_count(db_session, "pw@example.com") == 10


async def test_rate_limit_blocks_even_the_correct_password(client, db_session):
    # Otherwise an attacker who guesses correctly on attempt 11 still wins.
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    for _ in range(10):
        await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": "nope"})

    blocked = await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": PASSWORD})

    assert blocked.status_code == 429


async def test_rate_limit_is_per_email_not_global(client, db_session):
    await _seed_user(db_session, "busy@example.com", password=PASSWORD)
    await _seed_user(db_session, "calm@example.com", password=PASSWORD)

    for _ in range(10):
        await client.post(LOGIN_URL, json={"email": "busy@example.com", "password": "nope"})
    assert (
        await client.post(LOGIN_URL, json={"email": "busy@example.com", "password": PASSWORD})
    ).status_code == 429

    other = await client.post(LOGIN_URL, json={"email": "calm@example.com", "password": PASSWORD})

    assert other.status_code == 200, other.text


async def test_rate_limit_ignores_attempts_outside_the_window(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)
    stale = datetime.now(timezone.utc) - timedelta(minutes=16)
    for _ in range(10):
        db_session.add(LoginAttempt(email="pw@example.com", created_at=stale))
    await db_session.commit()

    resp = await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": PASSWORD})

    assert resp.status_code == 200, resp.text


async def test_rate_limit_bucket_is_case_insensitive(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    for casing in ("PW@example.com", "pw@Example.com", "pw@example.COM"):
        for _ in range(4):
            await client.post(LOGIN_URL, json={"email": casing, "password": "nope"})

    blocked = await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": "nope"})

    assert blocked.status_code == 429
    assert await _attempt_count(db_session, "pw@example.com") == 10


# --------------------------------------------------------------------------- #
# POST /auth/register — invite-gated password sign-up
# --------------------------------------------------------------------------- #


async def test_register_creates_account_with_password_and_signs_in(client, db_session):
    token = await _seed_club_invite(db_session)

    resp = await client.post(
        REGISTER_URL,
        json={"email": "new@example.com", "password": PASSWORD, "invite_token": token},
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["access_token"]
    assert resp.cookies.get("refresh_token")

    user = await db_session.scalar(select(User).where(User.email == "new@example.com"))
    assert user is not None
    assert user.password_hash is not None
    assert user.password_hash != PASSWORD


async def test_registered_account_can_then_log_in(client, db_session):
    token = await _seed_club_invite(db_session)
    await client.post(
        REGISTER_URL,
        json={"email": "new@example.com", "password": PASSWORD, "invite_token": token},
    )

    resp = await client.post(LOGIN_URL, json={"email": "new@example.com", "password": PASSWORD})

    assert resp.status_code == 200, resp.text


async def test_register_joins_the_invite_club(client, db_session):
    token = await _seed_club_invite(db_session)

    await client.post(
        REGISTER_URL,
        json={"email": "new@example.com", "password": PASSWORD, "invite_token": token},
    )

    invite = await db_session.scalar(select(Invite).where(Invite.token == token))
    user = await db_session.scalar(select(User).where(User.email == "new@example.com"))
    membership = await db_session.scalar(
        select(ClubMember).where(
            ClubMember.club_id == invite.club_id,
            ClubMember.user_id == user.id,
            ClubMember.removed_at.is_(None),
        )
    )
    assert membership is not None


async def test_register_normalizes_email_to_lowercase(client, db_session):
    token = await _seed_club_invite(db_session)

    resp = await client.post(
        REGISTER_URL,
        json={"email": "New@Example.COM", "password": PASSWORD, "invite_token": token},
    )

    assert resp.status_code == 201, resp.text
    assert await db_session.scalar(select(User).where(User.email == "new@example.com")) is not None


async def test_register_consumes_a_platform_invite(client, db_session):
    token = await _seed_platform_invite(db_session)

    resp = await client.post(
        REGISTER_URL,
        json={"email": "new@example.com", "password": PASSWORD, "invite_token": token},
    )

    assert resp.status_code == 201, resp.text
    await db_session.commit()
    invite = await db_session.scalar(select(Invite).where(Invite.token == token))
    user = await db_session.scalar(select(User).where(User.email == "new@example.com"))
    assert invite.used_at is not None
    assert invite.used_by_user_id == user.id


async def test_register_rejects_a_second_use_of_a_platform_invite(client, db_session):
    token = await _seed_platform_invite(db_session)
    await client.post(
        REGISTER_URL,
        json={"email": "first@example.com", "password": PASSWORD, "invite_token": token},
    )

    second = await client.post(
        REGISTER_URL,
        json={"email": "second@example.com", "password": PASSWORD, "invite_token": token},
    )

    assert second.status_code == 403
    assert second.json()["detail"] == _INVITE_REQUIRED


async def test_register_without_a_valid_invite_is_forbidden(client, db_session):
    resp = await client.post(
        REGISTER_URL,
        json={"email": "new@example.com", "password": PASSWORD, "invite_token": "no-such-token"},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == _INVITE_REQUIRED
    assert await db_session.scalar(select(User).where(User.email == "new@example.com")) is None


async def test_register_honors_the_invite_email_lock(client, db_session):
    token = await _seed_platform_invite(db_session, email="waiter@example.com")

    resp = await client.post(
        REGISTER_URL,
        json={"email": "someoneelse@example.com", "password": PASSWORD, "invite_token": token},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == _INVITE_REQUIRED


async def test_register_accepts_the_locked_email(client, db_session):
    token = await _seed_platform_invite(db_session, email="waiter@example.com")

    resp = await client.post(
        REGISTER_URL,
        json={"email": "waiter@example.com", "password": PASSWORD, "invite_token": token},
    )

    assert resp.status_code == 201, resp.text


async def test_register_conflicts_when_the_account_already_exists(client, db_session):
    token = await _seed_club_invite(db_session)
    await _seed_user(db_session, "taken@example.com")

    resp = await client.post(
        REGISTER_URL,
        json={"email": "taken@example.com", "password": PASSWORD, "invite_token": token},
    )

    assert resp.status_code == 409
    # The existing magic-link-only account is untouched.
    user = await db_session.scalar(select(User).where(User.email == "taken@example.com"))
    assert user.password_hash is None


async def test_register_with_a_bad_invite_hides_that_the_account_exists(client, db_session):
    # The 409 above is only acceptable to someone already holding a valid
    # invite. Without one, an existing address must be indistinguishable from
    # any other — otherwise this is an enumeration oracle over the whole users
    # table for anyone posting a garbage token.
    await _seed_user(db_session, "taken@example.com")

    resp = await client.post(
        REGISTER_URL,
        json={
            "email": "taken@example.com",
            "password": PASSWORD,
            "invite_token": "no-such-token",
        },
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == _INVITE_REQUIRED


async def test_register_with_a_bad_invite_answers_the_same_for_unknown_emails(client, db_session):
    # The other half of the pair: the response for an address that does NOT
    # exist has to be byte-identical to the one above.
    await _seed_user(db_session, "taken@example.com")

    taken = await client.post(
        REGISTER_URL,
        json={
            "email": "taken@example.com",
            "password": PASSWORD,
            "invite_token": "no-such-token",
        },
    )
    unknown = await client.post(
        REGISTER_URL,
        json={
            "email": "stranger@example.com",
            "password": PASSWORD,
            "invite_token": "no-such-token",
        },
    )

    assert taken.status_code == unknown.status_code == 403
    assert taken.json() == unknown.json()


async def test_register_with_an_email_locked_invite_hides_that_the_account_exists(
    client, db_session
):
    # An invite locked to someone else reads as "no invite" (MYS-215), so it
    # must not become an oracle either.
    await _seed_user(db_session, "taken@example.com")
    token = await _seed_platform_invite(db_session, email="waiter@example.com")

    resp = await client.post(
        REGISTER_URL,
        json={"email": "taken@example.com", "password": PASSWORD, "invite_token": token},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == _INVITE_REQUIRED


async def test_register_rejects_a_short_password(client, db_session):
    token = await _seed_club_invite(db_session)

    resp = await client.post(
        REGISTER_URL,
        json={"email": "new@example.com", "password": "short", "invite_token": token},
    )

    assert resp.status_code == 422
    assert await db_session.scalar(select(User).where(User.email == "new@example.com")) is None


async def test_register_requires_an_invite_token_field(client, db_session):
    resp = await client.post(REGISTER_URL, json={"email": "new@example.com", "password": PASSWORD})

    assert resp.status_code == 422


class TestRegisterUserCap:
    # Cap of 1 — the seeded organizer already fills it (MYS-127).
    @pytest.fixture
    def max_users(self) -> int:
        return 1

    async def test_password_signup_is_blocked_at_capacity(self, client, db_session):
        token = await _seed_club_invite(db_session)

        resp = await client.post(
            REGISTER_URL,
            json={"email": "overflow@example.com", "password": PASSWORD, "invite_token": token},
        )

        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "MysteryMixClub is at capacity right now"
        db_session.expire_all()
        assert (
            await db_session.scalar(select(User).where(User.email == "overflow@example.com"))
            is None
        )


# --------------------------------------------------------------------------- #
# Magic link is unchanged by any of the above.
# --------------------------------------------------------------------------- #


async def test_magic_link_signup_creates_an_account_with_no_password(client, db_session, email_spy):
    token = await _seed_club_invite(db_session)

    requested = await client.post(
        REQUEST_URL, json={"email": "magic@example.com", "invite_token": token}
    )
    assert requested.status_code == 200, requested.text
    raw = requested.json()["dev_token"]
    verified = await client.get(VERIFY_URL, params={"token": raw, "invite": token})

    assert verified.status_code == 200, verified.text
    user = await db_session.scalar(select(User).where(User.email == "magic@example.com"))
    assert user is not None
    assert user.password_hash is None


async def test_existing_password_account_can_still_use_magic_link(client, db_session, email_spy):
    await _seed_user(db_session, "both@example.com", password=PASSWORD)

    requested = await client.post(REQUEST_URL, json={"email": "both@example.com"})
    raw = requested.json()["dev_token"]
    verified = await client.get(VERIFY_URL, params={"token": raw})

    assert verified.status_code == 200, verified.text
    user = await db_session.scalar(select(User).where(User.email == "both@example.com"))
    # Signing in by link leaves the password in place.
    assert user.password_hash is not None


# --------------------------------------------------------------------------- #
# POST /auth/forgot-password
# --------------------------------------------------------------------------- #


async def test_forgot_password_mints_a_token_and_emails_a_link(client, db_session, email_spy):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    resp = await client.post(FORGOT_URL, json={"email": "pw@example.com"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == _RESET_NEUTRAL
    assert await _reset_token_count(db_session, "pw@example.com") == 1
    assert len(email_spy.reset_calls) == 1
    to, link = email_spy.reset_calls[0]
    assert to == "pw@example.com"
    assert "/auth/reset-password?token=" in link


async def test_forgot_password_stores_only_the_hash(client, db_session, email_spy):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    await client.post(FORGOT_URL, json={"email": "pw@example.com"})

    row = (await db_session.execute(select(PasswordResetToken))).scalar_one()
    raw = email_spy.reset_calls[0][1].split("token=")[1]
    assert row.token_hash != raw
    assert row.token_hash == hash_token(raw)


async def test_forgot_password_token_expires_in_30_minutes(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    await client.post(FORGOT_URL, json={"email": "pw@example.com"})

    row = (await db_session.execute(select(PasswordResetToken))).scalar_one()
    delta = row.expires_at - row.created_at
    assert abs(delta - timedelta(minutes=30)) < timedelta(seconds=5), delta


async def test_forgot_password_is_neutral_for_a_passwordless_account(client, db_session, email_spy):
    await _seed_user(db_session, "magiconly@example.com")

    resp = await client.post(FORGOT_URL, json={"email": "magiconly@example.com"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == _RESET_NEUTRAL
    assert "dev_token" not in resp.json()
    assert await _reset_token_count(db_session) == 0
    assert email_spy.reset_calls == []


async def test_forgot_password_is_neutral_for_an_unknown_email(client, db_session, email_spy):
    resp = await client.post(FORGOT_URL, json={"email": "nobody@example.com"})

    assert resp.status_code == 200, resp.text
    assert "dev_token" not in resp.json()
    assert await _reset_token_count(db_session) == 0
    assert email_spy.reset_calls == []


async def test_forgot_password_is_neutral_for_a_soft_deleted_account(client, db_session, email_spy):
    await _seed_user(
        db_session,
        "ghost@example.com",
        password=PASSWORD,
        deleted_at=datetime.now(timezone.utc),
    )

    resp = await client.post(FORGOT_URL, json={"email": "ghost@example.com"})

    assert resp.status_code == 200, resp.text
    assert await _reset_token_count(db_session) == 0
    assert email_spy.reset_calls == []


async def test_forgot_password_normalizes_email_case(client, db_session, email_spy):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    await client.post(FORGOT_URL, json={"email": "PW@Example.com"})

    row = (await db_session.execute(select(PasswordResetToken))).scalar_one()
    assert row.email == "pw@example.com"
    assert email_spy.reset_calls[0][0] == "pw@example.com"


async def test_forgot_password_rate_limit_five_then_429(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    for i in range(5):
        r = await client.post(FORGOT_URL, json={"email": "pw@example.com"})
        assert r.status_code == 200, f"request {i + 1} -> {r.status_code}"

    sixth = await client.post(FORGOT_URL, json={"email": "pw@example.com"})

    assert sixth.status_code == 429
    assert await _reset_token_count(db_session, "pw@example.com") == 5


async def test_forgot_password_rejects_an_invalid_email(client, db_session):
    resp = await client.post(FORGOT_URL, json={"email": "notanemail"})

    assert resp.status_code == 422
    assert await _reset_token_count(db_session) == 0


class _FailingEmailSender:
    """Email sender that always raises, simulating an unverified-domain / outage."""

    def send_magic_link(self, email: str, link: str) -> None:
        raise RuntimeError("domain is not verified")

    def send_password_reset(self, email: str, link: str) -> None:
        raise RuntimeError("domain is not verified")

    def send(self, email, subject, html, headers=None) -> None:
        raise RuntimeError("domain is not verified")


async def _client_with_failing_email(session_factory, environment: str):
    from httpx import ASGITransport, AsyncClient

    from app.config import Settings, get_settings
    from app.db.session import get_db
    from app.main import create_app
    from app.services.email import get_email_sender

    app = create_app()

    async def _override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_email_sender] = lambda: _FailingEmailSender()
    app.dependency_overrides[get_settings] = lambda: Settings(environment=environment)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_forgot_password_send_failure_outside_production_still_returns_a_dev_token(
    session_factory, db_session
):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    async with await _client_with_failing_email(session_factory, "staging") as ac:
        resp = await ac.post(FORGOT_URL, json={"email": "pw@example.com"})

    # Delivery failed, but the token is already persisted and usable.
    assert resp.status_code == 200, resp.text
    assert resp.json()["dev_token"]
    assert await _reset_token_count(db_session, "pw@example.com") == 1


async def test_forgot_password_send_failure_in_production_returns_502(session_factory, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)

    async with await _client_with_failing_email(session_factory, "production") as ac:
        resp = await ac.post(FORGOT_URL, json={"email": "pw@example.com"})

    # In production email is the only route to a reset, so surface a clean 502.
    assert resp.status_code == 502
    assert "dev_token" not in resp.json()


# --------------------------------------------------------------------------- #
# POST /auth/reset-password
# --------------------------------------------------------------------------- #


async def test_reset_password_sets_the_new_password(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)
    token = await _forgot_and_get_token(client, db_session, "pw@example.com")

    resp = await client.post(RESET_URL, json={"token": token, "password": NEW_PASSWORD})

    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "password updated"

    logged_in = await client.post(
        LOGIN_URL, json={"email": "pw@example.com", "password": NEW_PASSWORD}
    )
    assert logged_in.status_code == 200, logged_in.text


async def test_reset_password_retires_the_old_password(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)
    token = await _forgot_and_get_token(client, db_session, "pw@example.com")

    await client.post(RESET_URL, json={"token": token, "password": NEW_PASSWORD})

    stale = await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": PASSWORD})
    assert stale.status_code == 401


async def test_reset_token_is_single_use(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)
    token = await _forgot_and_get_token(client, db_session, "pw@example.com")

    first = await client.post(RESET_URL, json={"token": token, "password": NEW_PASSWORD})
    assert first.status_code == 200, first.text

    second = await client.post(RESET_URL, json={"token": token, "password": "another password"})

    assert second.status_code == 401
    assert second.json()["detail"] == _INVALID_LINK
    assert await _reset_token_count(db_session) == 0


async def test_expired_reset_token_is_rejected_and_consumed(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)
    token = await _forgot_and_get_token(client, db_session, "pw@example.com")
    row = (await db_session.execute(select(PasswordResetToken))).scalar_one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()

    resp = await client.post(RESET_URL, json={"token": token, "password": NEW_PASSWORD})

    assert resp.status_code == 401
    assert resp.json()["detail"] == _INVALID_LINK
    # An expired token is hard-deleted on lookup like a valid one.
    assert await _reset_token_count(db_session) == 0
    # And the old password still works.
    ok = await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": PASSWORD})
    assert ok.status_code == 200, ok.text


async def test_unknown_reset_token_is_rejected(client, db_session):
    resp = await client.post(RESET_URL, json={"token": "no-such-token", "password": NEW_PASSWORD})

    assert resp.status_code == 401
    assert resp.json()["detail"] == _INVALID_LINK


async def test_reset_password_rejects_a_short_password(client, db_session):
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)
    token = await _forgot_and_get_token(client, db_session, "pw@example.com")

    resp = await client.post(RESET_URL, json={"token": token, "password": "short"})

    assert resp.status_code == 422
    # The token is untouched by a rejected request, so the user can retry.
    assert await _reset_token_count(db_session) == 1


async def test_reset_password_invalidates_existing_sessions(client, db_session):
    user = await _seed_user(db_session, "pw@example.com", password=PASSWORD)
    user_id = user.id
    login = await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": PASSWORD})
    assert login.status_code == 200, login.text
    token = await _forgot_and_get_token(client, db_session, "pw@example.com")

    await client.post(RESET_URL, json={"token": token, "password": NEW_PASSWORD})

    sessions = (
        await db_session.execute(select(Session).where(Session.user_id == user_id))
    ).scalars()
    assert all(s.invalidated_at is not None for s in sessions)
    # The refresh cookie still in the client's jar is now dead.
    refreshed = await client.post(REFRESH_URL)
    assert refreshed.status_code == 401


async def test_reset_password_clears_the_login_lockout(client, db_session):
    # An attacker guessing at someone's address must not be able to lock them
    # out of the account they just recovered.
    await _seed_user(db_session, "pw@example.com", password=PASSWORD)
    for _ in range(10):
        await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": "nope"})
    assert (
        await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": PASSWORD})
    ).status_code == 429

    token = await _forgot_and_get_token(client, db_session, "pw@example.com")
    await client.post(RESET_URL, json={"token": token, "password": NEW_PASSWORD})

    assert await _attempt_count(db_session, "pw@example.com") == 0
    ok = await client.post(LOGIN_URL, json={"email": "pw@example.com", "password": NEW_PASSWORD})
    assert ok.status_code == 200, ok.text
