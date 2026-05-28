"""Tests for MYS-7: GET /api/v1/auth/verify (magic link verification + session issuance).

Covers happy path (token -> JWT + refresh cookie + user/session rows),
edge cases (existing-user re-login, expired token), and error states
(token reuse, garbage token, missing param). See technical-design.md §5, §6.

The soft-deleted-user-re-login case is intentionally NOT tested: the developer
flagged it out of MYS-7 scope (it raises on the UNIQUE email constraint and is
deferred to a §10 decision).
"""

from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import func, select

from app.auth.tokens import hash_token
from app.config import get_settings
from app.models.magic_link_token import MagicLinkToken
from app.models.session import Session
from app.models.user import User

REQUEST_URL = "/api/v1/auth/request"
VERIFY_URL = "/api/v1/auth/verify"
_JWT_ALGORITHM = "HS256"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _request_link(client, email_spy, email: str) -> str:
    """Request a magic link for ``email`` and return the raw token from the email."""
    resp = await client.post(REQUEST_URL, json={"email": email})
    assert resp.status_code == 200, f"request -> {resp.status_code}"
    _, link = email_spy.calls[-1]
    return link.split("token=")[1]


async def _count(db_session, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for attr, value in filters.items():
        stmt = stmt.where(getattr(model, attr) == value)
    return await db_session.scalar(stmt)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


async def test_verify_returns_200_with_bearer_token(client, email_spy):
    raw = await _request_link(client, email_spy, "alice@example.com")

    resp = await client.get(VERIFY_URL, params={"token": raw})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"access_token", "token_type"}
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]


async def test_jwt_decodes_with_correct_claims_and_60_min_ttl(
    client, email_spy, db_session
):
    settings = get_settings()
    raw = await _request_link(client, email_spy, "alice@example.com")

    resp = await client.get(VERIFY_URL, params={"token": raw})
    access_token = resp.json()["access_token"]

    claims = jwt.decode(access_token, settings.secret_key, algorithms=[_JWT_ALGORITHM])

    user = (await db_session.execute(select(User))).scalar_one()
    assert claims["sub"] == str(user.id)
    assert claims["exp"] - claims["iat"] == 3600


async def test_first_login_creates_user_with_empty_name_and_vibe_false(
    client, email_spy, db_session
):
    raw = await _request_link(client, email_spy, "alice@example.com")

    await client.get(VERIFY_URL, params={"token": raw})

    user = (await db_session.execute(select(User))).scalar_one()
    assert user.email == "alice@example.com"
    assert user.display_name == ""
    assert user.default_vibe_mode is False


async def test_session_row_stores_refresh_hash_not_raw_and_device_hint(
    client, email_spy, db_session
):
    raw = await _request_link(client, email_spy, "alice@example.com")

    resp = await client.get(
        VERIFY_URL,
        params={"token": raw},
        headers={"User-Agent": "MMCTestAgent/1.0"},
    )

    refresh_cookie = resp.cookies.get("refresh_token")
    assert refresh_cookie, "refresh_token cookie not set"

    session_row = (await db_session.execute(select(Session))).scalar_one()
    # Raw refresh token must NOT be stored; only its hash.
    assert session_row.refresh_token_hash != refresh_cookie
    assert session_row.refresh_token_hash == hash_token(refresh_cookie)
    # device_hint reflects the request User-Agent.
    assert session_row.device_hint == "MMCTestAgent/1.0"


async def test_refresh_cookie_attributes(client, email_spy):
    raw = await _request_link(client, email_spy, "alice@example.com")

    resp = await client.get(VERIFY_URL, params={"token": raw})

    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    lowered = set_cookie.lower()
    assert "httponly" in lowered, set_cookie
    assert "samesite=strict" in lowered, set_cookie
    assert "path=/api/v1/auth" in lowered, set_cookie
    assert "max-age=2592000" in lowered, set_cookie
    # Development env: cookie must NOT carry the Secure attribute.
    assert "secure" not in lowered, set_cookie


async def test_magic_link_token_deleted_after_successful_verify(
    client, email_spy, db_session
):
    raw = await _request_link(client, email_spy, "alice@example.com")
    assert await _count(db_session, MagicLinkToken) == 1

    resp = await client.get(VERIFY_URL, params={"token": raw})
    assert resp.status_code == 200

    # Single-use: the row is hard-deleted on a successful verify.
    assert await _count(db_session, MagicLinkToken) == 0


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #


async def test_second_login_same_email_one_user_two_sessions(
    client, email_spy, db_session
):
    email = "repeat@example.com"

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
    # Expire identity-map cache so the count reflects the committed DB state.
    db_session.expire_all()
    assert await _count(db_session, MagicLinkToken) == 0
    # No user or session should have been created.
    assert await _count(db_session, User) == 0
    assert await _count(db_session, Session) == 0


# --------------------------------------------------------------------------- #
# Error states
# --------------------------------------------------------------------------- #


async def test_reusing_token_second_call_401_no_extra_session(
    client, email_spy, db_session
):
    raw = await _request_link(client, email_spy, "alice@example.com")

    first = await client.get(VERIFY_URL, params={"token": raw})
    assert first.status_code == 200, first.text
    assert await _count(db_session, Session) == 1

    second = await client.get(VERIFY_URL, params={"token": raw})
    assert second.status_code == 401, second.text

    # No second session created on the reuse attempt.
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
