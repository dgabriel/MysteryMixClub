"""Tests for MysteryMixClub-ali8.4 (ADR 0007): account settings — set a
password / link Google on an existing account.

Covers POST /users/me/password and the GET /users/me/google/link ->
/auth/google/callback round trip. Doesn't re-test generic Google
sign-in-callback behavior already covered by test_auth_google.py (state
decode failures, exchange failures, unverified email) — only the link-flow
logic that's actually new: linking itself, the already-linked-elsewhere
conflict, and the link flow's own CSRF nonce check, which is new logic added
alongside the existing sign-in one (see app.auth.jwt.create_google_link_state).

PKs are captured into locals before any expire_all (project MissingGreenlet
gotcha).
"""

from collections.abc import AsyncGenerator
from urllib.parse import parse_qs, urlparse

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.auth.passwords import verify_password
from app.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.models.user import User
from app.services.google_oauth import GoogleIdentity, get_google_oauth_client

SET_PASSWORD_URL = "/api/v1/users/me/password"
GOOGLE_LINK_START_URL = "/api/v1/users/me/google/link"
CALLBACK_URL = "/api/v1/auth/google/callback"

GOOGLE_SUB = "google-sub-link-1234567890"


def _auth_header(user_id) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _seed_user(db_session, email: str, **overrides) -> User:
    user = User(email=email, display_name="", **overrides)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# --------------------------------------------------------------------------- #
# POST /users/me/password
# --------------------------------------------------------------------------- #


async def test_set_password_on_account_with_none(client, db_session):
    user = await _seed_user(db_session, "magiconly@example.com")
    user_id = user.id

    resp = await client.post(
        SET_PASSWORD_URL, json={"password": "a brand new password"}, headers=_auth_header(user_id)
    )
    assert resp.status_code == 201, resp.text

    await db_session.refresh(user)
    assert user.password_hash is not None
    assert verify_password(user.password_hash, "a brand new password")


async def test_set_password_conflict_when_already_set(client, db_session):
    from app.auth.passwords import hash_password

    user = await _seed_user(
        db_session, "haspw@example.com", password_hash=hash_password("existing password")
    )
    resp = await client.post(
        SET_PASSWORD_URL, json={"password": "a new one"}, headers=_auth_header(user.id)
    )
    assert resp.status_code == 409, resp.text
    assert "already set" in resp.json()["detail"]


async def test_set_password_requires_auth(client):
    resp = await client.post(SET_PASSWORD_URL, json={"password": "whatever password"})
    assert resp.status_code == 401


async def test_set_password_rejects_too_short(client, db_session):
    user = await _seed_user(db_session, "short@example.com")
    resp = await client.post(
        SET_PASSWORD_URL, json={"password": "short"}, headers=_auth_header(user.id)
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# GET /users/me/google/link (unconfigured Google -> the shared `client`
# fixture's default, no fake needed)
# --------------------------------------------------------------------------- #


async def test_google_link_start_requires_auth(client):
    resp = await client.get(GOOGLE_LINK_START_URL)
    assert resp.status_code == 401


async def test_google_link_start_404_when_unconfigured(client, db_session):
    user = await _seed_user(db_session, "nogoogle@example.com")
    resp = await client.get(GOOGLE_LINK_START_URL, headers=_auth_header(user.id))
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Configured-Google fixtures (mirrors test_auth_google.py's FakeGoogleOAuthClient
# approach: no network, no dependence on the ambient .env)
# --------------------------------------------------------------------------- #


class FakeGoogleOAuthClient:
    def __init__(self, *, identity: GoogleIdentity | None = None) -> None:
        self._identity = identity or GoogleIdentity(
            subject=GOOGLE_SUB, email="linker@example.com", email_verified=True
        )
        # PKCE (MysteryMixClub-ali8.7): recorded so a test can confirm the
        # verifier embedded in the link state is what actually gets sent.
        self.exchanged_verifiers: list[str] = []

    @property
    def is_configured(self) -> bool:
        return True

    def authorize_url(self, state: str, code_challenge: str) -> str:
        return (
            f"https://accounts.google.com/o/oauth2/v2/auth?state={state}"
            f"&code_challenge={code_challenge}"
        )

    async def exchange_code(self, code: str, code_verifier: str) -> str:
        self.exchanged_verifiers.append(code_verifier)
        return "google-access-token"

    async def fetch_identity(self, access_token: str) -> GoogleIdentity:
        return self._identity


@pytest_asyncio.fixture
async def fake_google() -> FakeGoogleOAuthClient:
    return FakeGoogleOAuthClient()


@pytest_asyncio.fixture
async def google_client(session_factory, fake_google) -> AsyncGenerator[AsyncClient, None]:
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_google_oauth_client] = lambda: fake_google
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="development", app_base_url="https://app.example.test"
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _outcome(response, key: str = "google_link") -> str:
    return parse_qs(urlparse(response.headers["location"]).query)[key][0]


async def _start_link(google_client, user_id) -> str:
    """Call the real start-link endpoint and return the signed state, leaving
    the nonce cookie in the client's jar the way a real browser would."""
    resp = await google_client.get(GOOGLE_LINK_START_URL, headers=_auth_header(user_id))
    assert resp.status_code == 200, resp.text
    return parse_qs(urlparse(resp.json()["authorize_url"]).query)["state"][0]


# --------------------------------------------------------------------------- #
# The link round trip
# --------------------------------------------------------------------------- #


async def test_link_google_success(google_client, db_session):
    user = await _seed_user(db_session, "linker@example.com")
    user_id = user.id

    state = await _start_link(google_client, user_id)
    resp = await google_client.get(CALLBACK_URL, params={"code": "auth-code", "state": state})

    assert resp.status_code == 303
    assert _outcome(resp) == "linked"
    assert "/profile?" in resp.headers["location"]

    await db_session.refresh(user)
    assert user.google_id == GOOGLE_SUB
    # The link flow must not touch the caller's existing session: no refresh
    # cookie is set on this response, unlike a sign-in callback's "ok".
    assert "refresh_token" not in resp.cookies


async def test_link_google_sends_matching_pkce_verifier(google_client, fake_google, db_session):
    """MysteryMixClub-ali8.7: the link flow shares the same code-exchange
    mechanism as sign-in, so it gets PKCE too -- not re-testing the
    challenge/S256 mechanics themselves (test_auth_google.py already does),
    just that the link state's verifier is the one actually sent."""
    from app.auth.jwt import decode_google_link_state

    user = await _seed_user(db_session, "pkce@example.com")
    state = await _start_link(google_client, user.id)
    expected_verifier = decode_google_link_state(state).code_verifier

    await google_client.get(CALLBACK_URL, params={"code": "auth-code", "state": state})

    assert fake_google.exchanged_verifiers == [expected_verifier]


async def test_link_google_conflict_when_identity_used_elsewhere(google_client, db_session):
    other = await _seed_user(db_session, "already@example.com", google_id=GOOGLE_SUB)
    user = await _seed_user(db_session, "wantslink@example.com")
    other_google_id, user_id = other.google_id, user.id

    state = await _start_link(google_client, user_id)
    resp = await google_client.get(CALLBACK_URL, params={"code": "auth-code", "state": state})

    assert _outcome(resp) == "already_linked_elsewhere"
    await db_session.refresh(user)
    await db_session.refresh(other)
    assert user.google_id is None
    assert other.google_id == other_google_id


async def test_link_google_nonce_mismatch_rejected(google_client, db_session):
    """The link flow's own CSRF nonce check (new alongside sign-in's) --
    completing the callback with the wrong/no cookie must not link anything."""
    user = await _seed_user(db_session, "victim@example.com")
    user_id = user.id

    state = await _start_link(google_client, user_id)
    google_client.cookies.clear()  # drop the nonce cookie the start call set

    resp = await google_client.get(CALLBACK_URL, params={"code": "auth-code", "state": state})

    assert _outcome(resp) == "invalid_state"
    await db_session.refresh(user)
    assert user.google_id is None
