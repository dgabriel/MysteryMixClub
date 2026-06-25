"""Tests for MYS-8: POST /api/v1/auth/refresh (silent token refresh flow).

Covers happy path (refresh cookie -> new JWT, last_used_at advanced, no token
rotation), and error states (missing cookie, unknown cookie, invalidated
session, expired session, neutral 401 detail). See technical-design.md §5
(Token Refresh Flow, Session Management, Security Rules).

Sessions are established end-to-end: request a magic link, capture the raw token
from the email spy, GET /auth/verify to mint a real session + refresh cookie.
For negative cases the cookie is controlled explicitly (passed per-request or the
session row is mutated directly via db_session).
"""

from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import select

from app.auth.tokens import hash_token
from app.config import get_settings
from app.models.session import Session
from app.models.user import User

REQUEST_URL = "/api/v1/auth/request"
VERIFY_URL = "/api/v1/auth/verify"
REFRESH_URL = "/api/v1/auth/refresh"
_JWT_ALGORITHM = "HS256"
_NEUTRAL_SESSION_DETAIL = "invalid or expired session"


# --------------------------------------------------------------------------- #
# Helpers
#
# v2 access model (MYS-127): /auth/request only mails a link to an EXISTING
# (non-deleted) user or someone arriving via a valid invite link. These
# session/refresh tests don't care how the account came to exist, so the helper
# seeds the user first, then runs the real magic-link flow.
# --------------------------------------------------------------------------- #


async def _seed_user(session_factory, email: str) -> None:
    """Idempotently ensure a non-deleted user exists for ``email``."""
    async with session_factory() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is None:
            db.add(User(email=email, display_name="", default_vibe_mode=False))
            await db.commit()


async def _request_link(client, email_spy, session_factory, email: str) -> str:
    """Seed the user, request a magic link, return the raw token from the email."""
    await _seed_user(session_factory, email)
    resp = await client.post(REQUEST_URL, json={"email": email})
    assert resp.status_code == 200, f"request -> {resp.status_code}: {resp.text}"
    _, link = email_spy.calls[-1]
    return link.split("token=")[1]


async def _establish_session(client, email_spy, session_factory, email: str) -> str:
    """Run request -> verify and return the raw refresh token cookie value.

    The same client's cookie jar also retains the cookie (path /api/v1/auth),
    so a subsequent /auth/refresh on this client carries it automatically.
    """
    raw = await _request_link(client, email_spy, session_factory, email)
    resp = await client.get(VERIFY_URL, params={"token": raw})
    assert resp.status_code == 200, resp.text
    refresh_cookie = resp.cookies.get("refresh_token")
    assert refresh_cookie, "verify did not set a refresh_token cookie"
    return refresh_cookie


async def _session_for_cookie(db_session, raw_cookie: str) -> Session:
    """Fetch the sessions row matching a raw refresh cookie value."""
    db_session.expire_all()
    return await db_session.scalar(
        select(Session).where(Session.refresh_token_hash == hash_token(raw_cookie))
    )


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


async def test_refresh_returns_200_with_bearer_token(client, email_spy, session_factory):
    await _establish_session(client, email_spy, session_factory, "alice@example.com")

    # Same client carries the refresh cookie set by /auth/verify automatically.
    resp = await client.post(REFRESH_URL)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"access_token", "token_type"}
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]


async def test_refresh_jwt_decodes_with_correct_claims_and_60_min_ttl(
    client, email_spy, db_session, session_factory
):
    settings = get_settings()
    raw_cookie = await _establish_session(client, email_spy, session_factory, "alice@example.com")

    resp = await client.post(REFRESH_URL)
    assert resp.status_code == 200, resp.text
    access_token = resp.json()["access_token"]

    claims = jwt.decode(access_token, settings.secret_key, algorithms=[_JWT_ALGORITHM])

    session = await _session_for_cookie(db_session, raw_cookie)
    assert session is not None
    assert claims["sub"] == str(session.user_id)
    assert claims["exp"] - claims["iat"] == 3600


async def test_refresh_advances_last_used_at(client, email_spy, db_session, session_factory):
    raw_cookie = await _establish_session(client, email_spy, session_factory, "alice@example.com")

    before = await _session_for_cookie(db_session, raw_cookie)
    assert before is not None
    last_used_after_verify = before.last_used_at

    resp = await client.post(REFRESH_URL)
    assert resp.status_code == 200, resp.text

    after = await _session_for_cookie(db_session, raw_cookie)
    assert after is not None
    assert after.last_used_at > last_used_after_verify, (
        f"last_used_at not advanced: verify={last_used_after_verify} refresh={after.last_used_at}"
    )


async def test_refresh_token_not_rotated_same_cookie_works_twice(
    client, email_spy, db_session, session_factory
):
    raw_cookie = await _establish_session(client, email_spy, session_factory, "alice@example.com")

    first = await client.post(REFRESH_URL)
    assert first.status_code == 200, first.text

    second = await client.post(REFRESH_URL)
    assert second.status_code == 200, second.text

    # The stored hash still matches the original raw cookie: not rotated.
    session = await _session_for_cookie(db_session, raw_cookie)
    assert session is not None
    assert session.refresh_token_hash == hash_token(raw_cookie)


# --------------------------------------------------------------------------- #
# Error states (each 401, neutral detail)
# --------------------------------------------------------------------------- #


async def test_no_refresh_cookie_returns_401(client):
    # Fresh client with an empty cookie jar; no cookie sent.
    resp = await client.post(REFRESH_URL)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == _NEUTRAL_SESSION_DETAIL


async def test_unknown_garbage_cookie_returns_401(client, db_session):
    resp = await client.post(
        REFRESH_URL, cookies={"refresh_token": "this-cookie-matches-no-session"}
    )

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == _NEUTRAL_SESSION_DETAIL


async def test_invalidated_session_returns_401(client, email_spy, db_session, session_factory):
    raw_cookie = await _establish_session(client, email_spy, session_factory, "alice@example.com")

    session = await _session_for_cookie(db_session, raw_cookie)
    assert session is not None
    session.invalidated_at = datetime.now(timezone.utc)
    await db_session.commit()

    # Send the captured cookie explicitly so this test owns the cookie state.
    resp = await client.post(REFRESH_URL, cookies={"refresh_token": raw_cookie})

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == _NEUTRAL_SESSION_DETAIL


async def test_expired_session_returns_401(client, email_spy, db_session, session_factory):
    raw_cookie = await _establish_session(client, email_spy, session_factory, "alice@example.com")

    session = await _session_for_cookie(db_session, raw_cookie)
    assert session is not None
    # created_at older than the 30-day window => server-side expiry.
    session.created_at = datetime.now(timezone.utc) - timedelta(days=31)
    await db_session.commit()

    resp = await client.post(REFRESH_URL, cookies={"refresh_token": raw_cookie})

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == _NEUTRAL_SESSION_DETAIL


async def test_401_detail_is_neutral_across_all_failure_modes(
    client, email_spy, db_session, session_factory
):
    # No cookie.
    no_cookie = await client.post(REFRESH_URL)

    # Unknown cookie.
    garbage = await client.post(REFRESH_URL, cookies={"refresh_token": "no-such-session"})

    # Invalidated session.
    raw_inv = await _establish_session(client, email_spy, session_factory, "inv@example.com")
    sess_inv = await _session_for_cookie(db_session, raw_inv)
    sess_inv.invalidated_at = datetime.now(timezone.utc)
    await db_session.commit()
    invalidated = await client.post(REFRESH_URL, cookies={"refresh_token": raw_inv})

    # Expired session.
    raw_exp = await _establish_session(client, email_spy, session_factory, "exp@example.com")
    sess_exp = await _session_for_cookie(db_session, raw_exp)
    sess_exp.created_at = datetime.now(timezone.utc) - timedelta(days=31)
    await db_session.commit()
    expired = await client.post(REFRESH_URL, cookies={"refresh_token": raw_exp})

    details = {
        no_cookie.json()["detail"],
        garbage.json()["detail"],
        invalidated.json()["detail"],
        expired.json()["detail"],
    }
    for r in (no_cookie, garbage, invalidated, expired):
        assert r.status_code == 401, r.text
    # All failure modes share one neutral detail: caller can't distinguish them.
    assert details == {_NEUTRAL_SESSION_DETAIL}, details
