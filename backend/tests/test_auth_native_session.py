"""Tests for MysteryMixClub-kw2u / ADR 0037: iOS app sessions without the cookie.

The iOS app's WebView origin (capacitor://localhost) is cross-site to the API,
so the SameSite=Lax refresh cookie never comes back. Instead:

- a sign-in from that Origin also returns the refresh token in the body (and
  only from that Origin -- a web caller never sees it);
- /auth/refresh, /auth/logout and /auth/logout-all accept it in the
  X-Refresh-Token header when no cookie is present;
- /auth/logout with no refresh token at all falls back to the Bearer access
  token's session, so logout always revokes (and drops that session's devices).

Every request here clears the client's cookie jar first, so nothing passes by
riding a cookie a previous call left behind.
"""

from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.auth.passwords import hash_password
from app.auth.tokens import hash_token
from app.config import get_settings
from app.models.device_push_token import DevicePushToken
from app.models.session import Session
from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"
LOGOUT_ALL_URL = "/api/v1/auth/logout-all"

NATIVE_ORIGIN = {"Origin": "capacitor://localhost"}
PASSWORD = "correct horse battery"


async def _seed_user(db_session, email: str) -> User:
    user = User(email=email, display_name="", password_hash=hash_password(PASSWORD))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _native_login(client, email: str) -> dict:
    client.cookies.clear()
    resp = await client.post(
        LOGIN_URL, json={"email": email, "password": PASSWORD}, headers=NATIVE_ORIGIN
    )
    assert resp.status_code == 200, resp.text
    client.cookies.clear()
    return resp.json()


async def _session_for(db_session, raw_refresh: str) -> Session:
    db_session.expire_all()
    return await db_session.scalar(
        select(Session).where(Session.refresh_token_hash == hash_token(raw_refresh))
    )


# --------------------------------------------------------------------------- #
# Sign-in: the refresh token is in the body for the iOS app only
# --------------------------------------------------------------------------- #


async def test_native_login_returns_the_refresh_token_in_the_body(client, db_session):
    user = await _seed_user(db_session, "ios@example.com")
    user_id = user.id

    body = await _native_login(client, "ios@example.com")

    assert body["access_token"]
    session = await _session_for(db_session, body["refresh_token"])
    assert session is not None
    assert session.user_id == user_id


async def test_web_login_never_returns_the_refresh_token(client, db_session):
    await _seed_user(db_session, "web@example.com")

    for headers in (
        {},
        {"Origin": "https://mysterymixclub.com"},
        {"Origin": "https://evil.example"},
    ):
        client.cookies.clear()
        resp = await client.post(
            LOGIN_URL, json={"email": "web@example.com", "password": PASSWORD}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert "refresh_token" not in resp.json(), headers
        # The web keeps working exactly as before: the cookie still carries it.
        assert resp.cookies.get("refresh_token")


# --------------------------------------------------------------------------- #
# Refresh with the header
# --------------------------------------------------------------------------- #


async def test_refresh_accepts_the_header_without_a_cookie(client, db_session):
    await _seed_user(db_session, "ios@example.com")
    body = await _native_login(client, "ios@example.com")

    resp = await client.post(REFRESH_URL, headers={"X-Refresh-Token": body["refresh_token"]})

    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]
    # A refresh never hands the refresh token back: the app already holds it.
    assert "refresh_token" not in resp.json()


async def test_refresh_with_an_unknown_header_token_returns_401(client, db_session):
    client.cookies.clear()
    resp = await client.post(REFRESH_URL, headers={"X-Refresh-Token": "not-a-real-token"})

    assert resp.status_code == 401, resp.text


# --------------------------------------------------------------------------- #
# Logout: header, then the Bearer fallback
# --------------------------------------------------------------------------- #


async def test_logout_with_the_header_revokes_the_session(client, db_session):
    await _seed_user(db_session, "ios@example.com")
    body = await _native_login(client, "ios@example.com")
    headers = {"X-Refresh-Token": body["refresh_token"]}

    resp = await client.post(LOGOUT_URL, headers=headers)

    assert resp.status_code == 200, resp.text
    session = await _session_for(db_session, body["refresh_token"])
    assert session.invalidated_at is not None
    client.cookies.clear()
    assert (await client.post(REFRESH_URL, headers=headers)).status_code == 401


async def test_logout_with_only_the_access_token_revokes_it_and_drops_its_devices(
    client, db_session
):
    """The fallback for an app with no refresh token to send (a lost Keychain
    entry, or a build from before ADR 0037): the access token's `sid` still
    identifies the session, so logout revokes it and deletes its devices even
    though the client's own DELETE never ran."""
    user = await _seed_user(db_session, "ios@example.com")
    user_id = user.id
    body = await _native_login(client, "ios@example.com")
    session = await _session_for(db_session, body["refresh_token"])
    session_id = session.id
    db_session.add(DevicePushToken(user_id=user_id, session_id=session_id, device_token="a" * 64))
    await db_session.commit()

    resp = await client.post(
        LOGOUT_URL, headers={"Authorization": f"Bearer {body['access_token']}"}
    )

    assert resp.status_code == 200, resp.text
    session = await _session_for(db_session, body["refresh_token"])
    assert session.invalidated_at is not None
    remaining = await db_session.scalar(
        select(DevicePushToken).where(DevicePushToken.session_id == session_id)
    )
    assert remaining is None


async def test_logout_with_an_invalid_access_token_is_a_harmless_200(client, db_session):
    await _seed_user(db_session, "ios@example.com")
    body = await _native_login(client, "ios@example.com")

    for authorization in ("Bearer garbage", "Basic abc", "Bearer "):
        resp = await client.post(LOGOUT_URL, headers={"Authorization": authorization})
        assert resp.status_code == 200, resp.text

    session = await _session_for(db_session, body["refresh_token"])
    assert session.invalidated_at is None


async def test_logout_with_an_expired_access_token_does_not_revoke(client, db_session):
    """Only a valid, unexpired access token identifies a session. An expired
    one is ignored (the app can refresh first, or send the header)."""
    await _seed_user(db_session, "ios@example.com")
    body = await _native_login(client, "ios@example.com")
    session = await _session_for(db_session, body["refresh_token"])
    # Same claims the app would hold, but past their expiry.
    claims = jwt.get_unverified_claims(create_access_token(session.user_id, session.id))
    claims["exp"] = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())
    expired = jwt.encode(claims, get_settings().secret_key, algorithm="HS256")

    resp = await client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {expired}"})

    assert resp.status_code == 200, resp.text
    session = await _session_for(db_session, body["refresh_token"])
    assert session.invalidated_at is None


async def test_logout_all_accepts_the_header(client, db_session):
    await _seed_user(db_session, "ios@example.com")
    first = await _native_login(client, "ios@example.com")
    second = await _native_login(client, "ios@example.com")

    resp = await client.post(LOGOUT_ALL_URL, headers={"X-Refresh-Token": first["refresh_token"]})

    assert resp.status_code == 200, resp.text
    for body in (first, second):
        session = await _session_for(db_session, body["refresh_token"])
        assert session.invalidated_at is not None
