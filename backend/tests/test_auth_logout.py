"""Tests for MYS-9: POST /api/v1/auth/logout and /auth/logout-all.

Covers:
- logout: happy path (active session invalidated, cookie cleared, 200), the
  refresh cross-check (invalidated session can no longer refresh), and
  idempotency (no cookie / garbage cookie still 200, never 401).
- logout-all: happy path (all of the user's active sessions invalidated, other
  users untouched, cookie cleared, 200), refresh cross-check on a sibling
  session, already-invalidated presenting cookie still works, and error states
  (no cookie / garbage cookie => 401 with neutral detail).

See technical-design.md §5 (Session Management — "Log out of all devices",
Security Rules) and §9 (Security Checklist).

Sessions are established end-to-end (request -> capture raw token from the email
spy -> GET /auth/verify). Cookie state is controlled explicitly per request so
cases never bleed across the shared client cookie jar.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.auth.tokens import hash_token
from app.models.session import Session
from app.models.user import User

REQUEST_URL = "/api/v1/auth/request"
VERIFY_URL = "/api/v1/auth/verify"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"
LOGOUT_ALL_URL = "/api/v1/auth/logout-all"

_NEUTRAL_SESSION_DETAIL = "invalid or expired session"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _request_link(client, email_spy, email: str) -> str:
    """Request a magic link for ``email`` and return the raw token from the email."""
    resp = await client.post(REQUEST_URL, json={"email": email})
    assert resp.status_code == 200, f"request -> {resp.status_code}: {resp.text}"
    _, link = email_spy.calls[-1]
    return link.split("token=")[1]


async def _establish_session(client, email_spy, email: str) -> str:
    """Run request -> verify and return the raw refresh token cookie value.

    NOTE: the shared client cookie jar also retains the cookie (path
    /api/v1/auth). Tests pass cookies explicitly to avoid jar bleed, and the
    captured raw value here is read off the verify Set-Cookie header.
    """
    raw = await _request_link(client, email_spy, email)
    resp = await client.get(VERIFY_URL, params={"token": raw})
    assert resp.status_code == 200, resp.text
    refresh_cookie = resp.cookies.get("refresh_token")
    assert refresh_cookie, "verify did not set a refresh_token cookie"
    return refresh_cookie


async def _session_for_cookie(db_session, raw_cookie: str) -> Session:
    """Fetch the sessions row matching a raw refresh cookie value (fresh read)."""
    db_session.expire_all()
    return await db_session.scalar(
        select(Session).where(Session.refresh_token_hash == hash_token(raw_cookie))
    )


async def _count(db_session, model, **filters) -> int:
    db_session.expire_all()
    stmt = select(func.count()).select_from(model)
    for attr, value in filters.items():
        stmt = stmt.where(getattr(model, attr) == value)
    return await db_session.scalar(stmt)


def _assert_cookie_cleared(resp) -> None:
    """The Set-Cookie on a logout response must clear refresh_token at the
    matching path (Max-Age=0 / expired). A cookie only clears when name+path
    match how it was set in /auth/verify."""
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie, set_cookie
    lowered = set_cookie.lower()
    assert "path=/api/v1/auth" in lowered, set_cookie
    # Starlette delete_cookie emits both max-age=0 and an expiry in the past.
    cleared = "max-age=0" in lowered or "expires=" in lowered
    assert cleared, f"cookie not cleared (no max-age=0 / expires): {set_cookie}"


# --------------------------------------------------------------------------- #
# logout — happy path
# --------------------------------------------------------------------------- #


async def test_logout_invalidates_session_and_clears_cookie(
    client, email_spy, db_session
):
    raw_cookie = await _establish_session(client, email_spy, "alice@example.com")

    before = await _session_for_cookie(db_session, raw_cookie)
    assert before is not None
    assert before.invalidated_at is None

    resp = await client.post(LOGOUT_URL, cookies={"refresh_token": raw_cookie})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"message": "logged out"}

    after = await _session_for_cookie(db_session, raw_cookie)
    assert after is not None
    assert after.invalidated_at is not None, "session was not invalidated"

    _assert_cookie_cleared(resp)


async def test_logout_then_refresh_with_same_token_returns_401(
    client, email_spy, db_session
):
    raw_cookie = await _establish_session(client, email_spy, "alice@example.com")

    logout_resp = await client.post(LOGOUT_URL, cookies={"refresh_token": raw_cookie})
    assert logout_resp.status_code == 200, logout_resp.text

    # The now-invalidated session can no longer mint access tokens.
    refresh_resp = await client.post(
        REFRESH_URL, cookies={"refresh_token": raw_cookie}
    )
    assert refresh_resp.status_code == 401, refresh_resp.text
    assert refresh_resp.json()["detail"] == _NEUTRAL_SESSION_DETAIL


# --------------------------------------------------------------------------- #
# logout — idempotency (never 401)
# --------------------------------------------------------------------------- #


async def test_logout_no_cookie_returns_200(client):
    # Fresh client cookie jar, no cookie sent.
    resp = await client.post(LOGOUT_URL)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"message": "logged out"}
    _assert_cookie_cleared(resp)


async def test_logout_garbage_cookie_returns_200(client):
    resp = await client.post(
        LOGOUT_URL, cookies={"refresh_token": "this-cookie-matches-no-session"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"message": "logged out"}
    _assert_cookie_cleared(resp)


async def test_logout_already_invalidated_cookie_returns_200(
    client, email_spy, db_session
):
    raw_cookie = await _establish_session(client, email_spy, "alice@example.com")

    session = await _session_for_cookie(db_session, raw_cookie)
    assert session is not None
    session.invalidated_at = datetime.now(timezone.utc)
    await db_session.commit()
    already_invalidated_at = session.invalidated_at

    resp = await client.post(LOGOUT_URL, cookies={"refresh_token": raw_cookie})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"message": "logged out"}

    # Idempotent: the existing invalidation timestamp is not disturbed.
    after = await _session_for_cookie(db_session, raw_cookie)
    assert after is not None
    assert after.invalidated_at == already_invalidated_at


# --------------------------------------------------------------------------- #
# logout-all — happy path
# --------------------------------------------------------------------------- #


async def test_logout_all_invalidates_all_user_sessions_only(
    client, email_spy, db_session
):
    # Two sessions for the same user.
    raw_a1 = await _establish_session(client, email_spy, "user1@example.com")
    raw_a2 = await _establish_session(client, email_spy, "user1@example.com")
    # One session for a different user.
    raw_b = await _establish_session(client, email_spy, "user2@example.com")

    assert await _count(db_session, User, email="user1@example.com") == 1
    assert await _count(db_session, Session) == 3

    # Capture user_id eagerly per fetch: _session_for_cookie expires the
    # identity map on each call, so holding stale ORM refs would trigger a
    # synchronous lazy-reload. Read the scalar before the next fetch.
    sess_a1 = await _session_for_cookie(db_session, raw_a1)
    assert sess_a1 is not None
    user1_id = sess_a1.user_id
    sess_a2 = await _session_for_cookie(db_session, raw_a2)
    assert sess_a2 is not None
    user1_id_again = sess_a2.user_id
    sess_b = await _session_for_cookie(db_session, raw_b)
    assert sess_b is not None
    user2_id = sess_b.user_id
    assert user1_id == user1_id_again
    assert user2_id != user1_id

    resp = await client.post(LOGOUT_ALL_URL, cookies={"refresh_token": raw_a1})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"message": "logged out of all devices"}

    # Both of user1's sessions are invalidated. Read invalidated_at eagerly per
    # fetch (see note above) so the later expire_all can't trigger a reload.
    after_a1 = await _session_for_cookie(db_session, raw_a1)
    assert after_a1 is not None
    a1_invalidated = after_a1.invalidated_at
    after_a2 = await _session_for_cookie(db_session, raw_a2)
    assert after_a2 is not None
    a2_invalidated = after_a2.invalidated_at
    after_b = await _session_for_cookie(db_session, raw_b)
    assert after_b is not None
    b_invalidated = after_b.invalidated_at

    assert a1_invalidated is not None
    assert a2_invalidated is not None, "sibling session not invalidated"
    # user2's session is untouched.
    assert b_invalidated is None, "other user's session was invalidated"

    _assert_cookie_cleared(resp)


async def test_logout_all_then_refresh_with_other_session_returns_401(
    client, email_spy, db_session
):
    raw_a1 = await _establish_session(client, email_spy, "user1@example.com")
    raw_a2 = await _establish_session(client, email_spy, "user1@example.com")

    logout_resp = await client.post(
        LOGOUT_ALL_URL, cookies={"refresh_token": raw_a1}
    )
    assert logout_resp.status_code == 200, logout_resp.text

    # The OTHER (not-presented) session can no longer refresh.
    refresh_resp = await client.post(
        REFRESH_URL, cookies={"refresh_token": raw_a2}
    )
    assert refresh_resp.status_code == 401, refresh_resp.text
    assert refresh_resp.json()["detail"] == _NEUTRAL_SESSION_DETAIL


async def test_logout_all_with_already_invalidated_presenting_cookie(
    client, email_spy, db_session
):
    raw_a1 = await _establish_session(client, email_spy, "user1@example.com")
    raw_a2 = await _establish_session(client, email_spy, "user1@example.com")

    # Invalidate the presenting session directly.
    presenting = await _session_for_cookie(db_session, raw_a1)
    assert presenting is not None
    presenting.invalidated_at = datetime.now(timezone.utc)
    await db_session.commit()

    # logout-all looks up by hash regardless of the presenting session's own
    # invalidated state, so it still resolves the user and acts on the rest.
    resp = await client.post(LOGOUT_ALL_URL, cookies={"refresh_token": raw_a1})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"message": "logged out of all devices"}

    after_a2 = await _session_for_cookie(db_session, raw_a2)
    assert after_a2 is not None
    assert after_a2.invalidated_at is not None, (
        "other active session not invalidated when presenting an "
        "already-invalidated cookie"
    )

    _assert_cookie_cleared(resp)


# --------------------------------------------------------------------------- #
# logout-all — error states (401, neutral detail)
# --------------------------------------------------------------------------- #


async def test_logout_all_no_cookie_returns_401(client, db_session):
    resp = await client.post(LOGOUT_ALL_URL)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == _NEUTRAL_SESSION_DETAIL


async def test_logout_all_garbage_cookie_returns_401(client, db_session):
    resp = await client.post(
        LOGOUT_ALL_URL, cookies={"refresh_token": "no-such-session"}
    )

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == _NEUTRAL_SESSION_DETAIL
