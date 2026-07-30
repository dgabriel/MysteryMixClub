"""Tests for MysteryMixClub-ali8.2 (ADR 0007): Google Sign-In.

Google's consent screen can't be driven by an automated test, so the flow is
exercised end to end with a ``FakeGoogleOAuthClient`` standing in for the token
exchange and userinfo lookup (mirroring ``test_spotify_routes.py``'s approach —
no network, no dependence on the ambient .env). Everything else is real: the
signed state, the nonce cookie, account resolution, and the session cookie.

The round-trip helper calls ``/auth/google/login`` first and reuses its state +
cookie jar, so the tests cover the two endpoints as an actual pair rather than
hand-crafting states the login endpoint would never mint.

PKs are captured into locals before any expire_all (project MissingGreenlet
gotcha).
"""

import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token, create_oauth_state, create_sign_in_state
from app.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.invite import Invite
from app.models.session import Session
from app.models.user import User
from app.services.email import get_email_sender
from app.services.google_oauth import (
    GoogleApiError,
    GoogleAuthError,
    GoogleIdentity,
    get_google_oauth_client,
)

LOGIN_URL = "/api/v1/auth/google/login"
CALLBACK_URL = "/api/v1/auth/google/callback"
ENABLED_URL = "/api/v1/auth/google/enabled"
REFRESH_URL = "/api/v1/auth/refresh"

GOOGLE_SUB = "google-sub-1234567890"


# --------------------------------------------------------------------------- #
# Fake client + local app (no network)
# --------------------------------------------------------------------------- #


class FakeGoogleOAuthClient:
    """Stands in for GoogleOAuthClient. Returns a fixed identity and records the
    codes it was asked to exchange."""

    def __init__(
        self,
        *,
        configured: bool = True,
        identity: GoogleIdentity | None = None,
        exchange_raises: Exception | None = None,
        identity_raises: Exception | None = None,
    ) -> None:
        self._configured = configured
        self._identity = identity or GoogleIdentity(
            subject=GOOGLE_SUB, email="newcomer@example.com", email_verified=True
        )
        self._exchange_raises = exchange_raises
        self._identity_raises = identity_raises
        self.exchanged_codes: list[str] = []
        # PKCE (MysteryMixClub-ali8.7): recorded so tests can confirm the same
        # verifier minted at /google/login is the one sent at exchange time.
        self.exchanged_verifiers: list[str] = []

    @property
    def is_configured(self) -> bool:
        return self._configured

    def authorize_url(self, state: str, code_challenge: str) -> str:
        return (
            f"https://accounts.google.com/o/oauth2/v2/auth?state={state}"
            f"&code_challenge={code_challenge}&code_challenge_method=S256"
        )

    async def exchange_code(self, code: str, code_verifier: str) -> str:
        if self._exchange_raises:
            raise self._exchange_raises
        self.exchanged_codes.append(code)
        self.exchanged_verifiers.append(code_verifier)
        return "google-access-token"

    async def fetch_identity(self, access_token: str) -> GoogleIdentity:
        if self._identity_raises:
            raise self._identity_raises
        return self._identity


def _build_app(session_factory, fake, email_spy):
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_google_oauth_client] = lambda: fake
    app.dependency_overrides[get_email_sender] = lambda: email_spy
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="development", app_base_url="https://app.example.test"
    )
    return app


@pytest_asyncio.fixture
async def fake_google() -> FakeGoogleOAuthClient:
    return FakeGoogleOAuthClient()


@pytest_asyncio.fixture
async def google_client(
    session_factory, fake_google, email_spy
) -> AsyncGenerator[AsyncClient, None]:
    app = _build_app(session_factory, fake_google, email_spy)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Seeding + flow helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, **overrides) -> User:
    user = User(email=email, display_name="", **overrides)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_club_invite(db_session) -> str:
    organizer = User(email="org@example.com", display_name="Org")
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


def _state_from(response) -> str:
    """Pull the signed state out of the consent-screen URL the login endpoint
    redirected to."""
    query = parse_qs(urlparse(response.headers["location"]).query)
    return query["state"][0]


def _outcome(response) -> str:
    """The ?google= flag the callback landed the browser on."""
    return parse_qs(urlparse(response.headers["location"]).query)["google"][0]


async def _start_flow(client, invite_token: str | None = None) -> str:
    """Run /auth/google/login and return the state, leaving the nonce cookie in
    the client's jar the way a real browser would."""
    params = {"invite_token": invite_token} if invite_token else None
    resp = await client.get(LOGIN_URL, params=params)
    assert resp.status_code == 302, resp.text
    return _state_from(resp)


async def _round_trip(client, invite_token: str | None = None, code: str = "auth-code"):
    """The whole flow: login -> Google -> callback."""
    state = await _start_flow(client, invite_token)
    return await client.get(CALLBACK_URL, params={"code": code, "state": state})


@contextmanager
def _capture_auth_warnings():
    """Collect WARNING messages from the auth logger.

    Not ``caplog``: ``app/main.py`` sets ``propagate = False`` on the ``app``
    logger in development, so records never reach the root logger caplog
    listens on. Attaching to the logger itself is what actually observes them.
    """
    messages: list[str] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    logger = logging.getLogger("app.api.routes.auth")
    handler = _Collector(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        yield messages
    finally:
        logger.removeHandler(handler)


# --------------------------------------------------------------------------- #
# GET /auth/google/login
# --------------------------------------------------------------------------- #


async def test_login_redirects_to_google(google_client):
    resp = await google_client.get(LOGIN_URL)

    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://accounts.google.com/")


async def test_login_sets_a_nonce_cookie(google_client):
    resp = await google_client.get(LOGIN_URL)

    assert resp.cookies.get("google_oauth_nonce")


async def test_login_redirect_carries_a_pkce_challenge(google_client):
    """MysteryMixClub-ali8.7: the consent URL must carry Google's expected
    PKCE params, not just our own state/nonce."""
    resp = await google_client.get(LOGIN_URL)
    query = parse_qs(urlparse(resp.headers["location"]).query)

    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) > 0


async def test_callback_sends_the_matching_code_verifier_to_exchange(google_client, fake_google):
    """MysteryMixClub-ali8.7: the verifier minted at /login must be exactly
    the one sent back to Google at exchange time, not a fresh one."""
    from app.auth.jwt import decode_sign_in_state

    state = await _start_flow(google_client)
    expected_verifier = decode_sign_in_state(state).code_verifier

    await google_client.get(CALLBACK_URL, params={"code": "auth-code", "state": state})

    assert fake_google.exchanged_verifiers == [expected_verifier]


async def test_login_state_carries_the_invite_token(google_client):
    from app.auth.jwt import decode_sign_in_state

    resp = await google_client.get(LOGIN_URL, params={"invite_token": "tok_abc"})

    assert decode_sign_in_state(_state_from(resp)).invite_token == "tok_abc"


async def test_login_state_nonce_matches_the_cookie(google_client):
    from app.auth.jwt import decode_sign_in_state

    resp = await google_client.get(LOGIN_URL)

    assert decode_sign_in_state(_state_from(resp)).nonce == resp.cookies["google_oauth_nonce"]


async def test_login_is_404_when_unconfigured(session_factory, email_spy):
    app = _build_app(session_factory, FakeGoogleOAuthClient(configured=False), email_spy)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(LOGIN_URL)

    assert resp.status_code == 404


async def test_callback_is_404_when_unconfigured(session_factory, email_spy):
    app = _build_app(session_factory, FakeGoogleOAuthClient(configured=False), email_spy)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(CALLBACK_URL, params={"code": "c", "state": "s"})

    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# GET /auth/google/enabled — lets the login screen hide the button rather than
# render one that would just 404 (the contract in docs/staging-setup.md).
# --------------------------------------------------------------------------- #


async def test_enabled_is_true_when_configured(google_client):
    resp = await google_client.get(ENABLED_URL)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enabled": True}


async def test_enabled_is_false_when_unconfigured(session_factory, email_spy):
    app = _build_app(session_factory, FakeGoogleOAuthClient(configured=False), email_spy)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(ENABLED_URL)

    # 200 with enabled=false, NOT a 404 like /google/login — the frontend has to
    # be able to ask the question and get an answer either way.
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enabled": False}


async def test_enabled_needs_no_authentication(session_factory, email_spy):
    # It's consulted on the login screen, before anyone has a session.
    app = _build_app(session_factory, FakeGoogleOAuthClient(configured=False), email_spy)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(ENABLED_URL)

    assert resp.status_code != 401


# --------------------------------------------------------------------------- #
# New account — invite-gated, exactly like magic link and password sign-up
# --------------------------------------------------------------------------- #


async def test_new_account_with_valid_invite_is_created(google_client, db_session):
    invite_token = await _seed_club_invite(db_session)

    resp = await _round_trip(google_client, invite_token)

    assert resp.status_code == 303, resp.text
    assert _outcome(resp) == "ok"
    user = await db_session.scalar(select(User).where(User.email == "newcomer@example.com"))
    assert user is not None
    assert user.google_id == GOOGLE_SUB


async def test_new_account_gets_a_session_cookie(google_client, db_session):
    invite_token = await _seed_club_invite(db_session)

    resp = await _round_trip(google_client, invite_token)

    assert resp.cookies.get("refresh_token")


async def test_new_account_session_works_for_refresh(google_client, db_session):
    # The redirect hands back no access token by design; the SPA's on-mount
    # /auth/refresh is what turns the cookie into one.
    invite_token = await _seed_club_invite(db_session)

    await _round_trip(google_client, invite_token)
    refreshed = await google_client.post(REFRESH_URL)

    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["access_token"]


async def test_new_account_joins_the_invite_club(google_client, db_session):
    invite_token = await _seed_club_invite(db_session)

    await _round_trip(google_client, invite_token)

    invite = await db_session.scalar(select(Invite).where(Invite.token == invite_token))
    user = await db_session.scalar(select(User).where(User.email == "newcomer@example.com"))
    membership = await db_session.scalar(
        select(ClubMember).where(
            ClubMember.club_id == invite.club_id,
            ClubMember.user_id == user.id,
            ClubMember.removed_at.is_(None),
        )
    )
    assert membership is not None


async def test_new_account_without_an_invite_is_rejected(google_client, db_session):
    resp = await _round_trip(google_client)

    assert _outcome(resp) == "invite_required"
    assert await db_session.scalar(select(User).where(User.email == "newcomer@example.com")) is None
    assert "refresh_token" not in resp.cookies


async def test_new_account_with_an_unknown_invite_is_rejected(google_client, db_session):
    resp = await _round_trip(google_client, "no-such-invite")

    assert _outcome(resp) == "invite_required"
    assert await db_session.scalar(select(User).where(User.email == "newcomer@example.com")) is None


# --------------------------------------------------------------------------- #
# Existing account — linked by verified email, NOT invite-gated
# --------------------------------------------------------------------------- #


async def test_existing_email_is_linked_without_an_invite(google_client, db_session):
    # The account already exists and Google just proved ownership of its
    # address, so no invite is required to sign in.
    user = await _seed_user(db_session, "newcomer@example.com")
    user_id = user.id

    resp = await _round_trip(google_client)

    assert _outcome(resp) == "ok"
    db_session.expire_all()
    linked = await db_session.scalar(select(User).where(User.id == user_id))
    assert linked.google_id == GOOGLE_SUB


async def test_existing_email_link_does_not_create_a_second_account(google_client, db_session):
    await _seed_user(db_session, "newcomer@example.com")

    await _round_trip(google_client)

    db_session.expire_all()
    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == "newcomer@example.com")
    )
    assert count == 1


async def test_already_linked_account_signs_in_by_google_id(google_client, db_session):
    # Google's `sub` is the identity, not the address — a user who changed their
    # Gmail address still resolves to the same account.
    user = await _seed_user(db_session, "old-address@example.com", google_id=GOOGLE_SUB)
    user_id = user.id

    resp = await _round_trip(google_client)

    assert _outcome(resp) == "ok"
    db_session.expire_all()
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
    session_row = await db_session.scalar(select(Session).where(Session.user_id == user_id))
    assert session_row is not None


async def test_existing_link_is_replaced_by_the_current_google_identity(google_client, db_session):
    # Whoever controls the verified address now is the rightful owner, so the
    # new identity wins — leaving the stale link would lock them out of their
    # own account. The relink is logged as an audit trail, since to a user
    # reviewing their linked identities later a silent swap would be
    # indistinguishable from a hijack.
    user = await _seed_user(db_session, "newcomer@example.com", google_id="some-other-sub")
    user_id = user.id

    with _capture_auth_warnings() as warnings:
        resp = await _round_trip(google_client)

    assert _outcome(resp) == "ok"
    db_session.expire_all()
    relinked = await db_session.scalar(select(User).where(User.id == user_id))
    assert relinked.google_id == GOOGLE_SUB
    # A session was issued, i.e. the relink is a real sign-in, not a no-op.
    assert await db_session.scalar(select(Session).where(Session.user_id == user_id)) is not None
    relink_logs = [m for m in warnings if "relinking" in m]
    assert relink_logs, warnings
    assert "some-other-sub" in relink_logs[0]
    assert GOOGLE_SUB in relink_logs[0]


async def test_filling_in_a_blank_link_is_not_logged_as_a_relink(google_client, db_session):
    # The warning is for *replacing* a live link; the ordinary first-time link
    # must stay quiet or the signal is worthless.
    await _seed_user(db_session, "newcomer@example.com")

    with _capture_auth_warnings() as warnings:
        await _round_trip(google_client)

    assert not any("relinking" in m for m in warnings), warnings


async def test_soft_deleted_account_does_not_match(google_client, db_session):
    # A deleted account must not be resurrected by signing in with Google; with
    # no invite this is just an ordinary blocked new sign-up.
    await _seed_user(
        db_session,
        "newcomer@example.com",
        deleted_at=datetime.now(timezone.utc),
    )

    resp = await _round_trip(google_client)

    assert _outcome(resp) == "invite_required"


async def test_account_deletion_clears_the_google_link(google_client, db_session):
    # google_id is a third-party identifier for someone who asked to be
    # forgotten, so deletion has to drop it (TD 10) — the same reason the
    # password hash goes.
    invite_token = await _seed_club_invite(db_session)
    await _round_trip(google_client, invite_token)
    user = await db_session.scalar(select(User).where(User.email == "newcomer@example.com"))
    user_id = user.id

    resp = await google_client.delete(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {create_access_token(user_id)}"}
    )
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    tombstone = await db_session.scalar(select(User).where(User.id == user_id))
    assert tombstone.deleted_at is not None
    assert tombstone.google_id is None


async def test_signup_succeeds_after_the_same_google_account_was_deleted(google_client, db_session):
    # The real regression: both lookups in _resolve_google_account filter
    # deleted_at IS NULL, so a tombstone that kept its google_id is invisible to
    # them and the INSERT collides on uq_users_google_id — an IntegrityError,
    # not an HTTPException, so a 500 rather than a clean redirect. Driven
    # through the actual delete endpoint so it exercises the fix rather than a
    # hand-made tombstone.
    invite_token = await _seed_club_invite(db_session)
    await _round_trip(google_client, invite_token)
    first = await db_session.scalar(select(User).where(User.email == "newcomer@example.com"))
    first_id = first.id
    await google_client.delete(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {create_access_token(first_id)}"}
    )
    google_client.cookies.clear()

    resp = await _round_trip(google_client, invite_token)

    assert resp.status_code == 303, resp.text
    assert _outcome(resp) == "ok"
    db_session.expire_all()
    fresh = await db_session.scalar(
        select(User).where(User.email == "newcomer@example.com", User.deleted_at.is_(None))
    )
    assert fresh is not None
    assert fresh.id != first_id
    assert fresh.google_id == GOOGLE_SUB


async def test_google_id_is_unique_across_accounts(google_client, db_session):
    # The DB constraint is the backstop behind the resolution logic.
    await _seed_user(db_session, "first@example.com", google_id=GOOGLE_SUB)

    import sqlalchemy.exc

    db_session.add(User(email="second@example.com", display_name="", google_id=GOOGLE_SUB))
    try:
        await db_session.commit()
        raised = False
    except sqlalchemy.exc.IntegrityError:
        raised = True
        await db_session.rollback()

    assert raised, "expected a unique-constraint violation on google_id"


# --------------------------------------------------------------------------- #
# State / nonce rejection
# --------------------------------------------------------------------------- #


async def test_tampered_state_is_rejected(google_client, db_session):
    await _start_flow(google_client)

    resp = await google_client.get(
        CALLBACK_URL, params={"code": "auth-code", "state": "not-a-real-state"}
    )

    assert _outcome(resp) == "invalid_state"
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


async def test_state_without_the_nonce_cookie_is_rejected(google_client, db_session):
    # An attacker who starts their own flow and feeds the victim the resulting
    # callback URL has a valid signed state but no matching cookie in the
    # victim's browser (login-CSRF).
    state = await _start_flow(google_client)
    google_client.cookies.clear()

    resp = await google_client.get(CALLBACK_URL, params={"code": "auth-code", "state": state})

    assert _outcome(resp) == "invalid_state"
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


async def test_mismatched_nonce_cookie_is_rejected(google_client, db_session):
    state = await _start_flow(google_client)
    google_client.cookies.set("google_oauth_nonce", "some-other-nonce")

    resp = await google_client.get(CALLBACK_URL, params={"code": "auth-code", "state": state})

    assert _outcome(resp) == "invalid_state"


async def test_non_ascii_nonce_cookie_is_rejected_cleanly(google_client, db_session):
    # secrets.compare_digest raises TypeError on a non-ASCII str, and the cookie
    # is fully attacker-controlled — this must read as "doesn't match", not 500.
    # Sent as a raw header rather than through the cookie jar: httpx refuses to
    # encode non-ASCII into a cookie, but an attacker with curl has no such
    # scruples, and the header arrives decoded into a non-ASCII str either way.
    state = await _start_flow(google_client)
    google_client.cookies.clear()

    resp = await google_client.get(
        CALLBACK_URL,
        params={"code": "auth-code", "state": state},
        headers=[(b"cookie", "google_oauth_nonce=nönce-ünicode".encode("utf-8"))],
    )

    assert resp.status_code == 303, resp.text
    assert _outcome(resp) == "invalid_state"
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


async def test_state_from_another_purpose_is_rejected(google_client, db_session):
    # A Spotify-connect state must not be replayable against the sign-in callback.
    foreign = create_oauth_state(uuid.uuid4(), "spotify", None)

    resp = await google_client.get(CALLBACK_URL, params={"code": "auth-code", "state": foreign})

    assert _outcome(resp) == "invalid_state"


async def test_state_signed_elsewhere_is_rejected(google_client, db_session):
    # Correct shape, wrong signature.
    from jose import jwt

    forged = jwt.encode(
        {"nonce": "n", "purpose": "sign_in", "exp": 9999999999}, "not-the-secret", algorithm="HS256"
    )
    google_client.cookies.set("google_oauth_nonce", "n")

    resp = await google_client.get(CALLBACK_URL, params={"code": "auth-code", "state": forged})

    assert _outcome(resp) == "invalid_state"


async def test_missing_state_is_treated_as_denied(google_client):
    resp = await google_client.get(CALLBACK_URL, params={"code": "auth-code"})

    assert _outcome(resp) == "denied"


async def test_consent_denied_is_reported(google_client, db_session):
    state = await _start_flow(google_client)

    resp = await google_client.get(CALLBACK_URL, params={"error": "access_denied", "state": state})

    assert _outcome(resp) == "denied"
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


# --------------------------------------------------------------------------- #
# Google-side failures
# --------------------------------------------------------------------------- #


async def test_unverified_email_is_refused(session_factory, db_session, email_spy):
    fake = FakeGoogleOAuthClient(
        identity=GoogleIdentity(
            subject=GOOGLE_SUB, email="unverified@example.com", email_verified=False
        )
    )
    app = _build_app(session_factory, fake, email_spy)
    await _seed_club_invite(db_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await _round_trip(ac)

    assert _outcome(resp) == "email_unverified"
    assert (
        await db_session.scalar(select(User).where(User.email == "unverified@example.com")) is None
    )


async def test_unverified_email_cannot_hijack_an_existing_account(
    session_factory, db_session, email_spy
):
    # The whole point of checking email_verified: an unverified Google address
    # must never link to an account that owns that address for real.
    fake = FakeGoogleOAuthClient(
        identity=GoogleIdentity(
            subject=GOOGLE_SUB, email="victim@example.com", email_verified=False
        )
    )
    app = _build_app(session_factory, fake, email_spy)
    user = await _seed_user(db_session, "victim@example.com")
    user_id = user.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await _round_trip(ac)

    assert _outcome(resp) == "email_unverified"
    db_session.expire_all()
    untouched = await db_session.scalar(select(User).where(User.id == user_id))
    assert untouched.google_id is None


async def test_code_exchange_failure_is_reported(session_factory, db_session, email_spy):
    fake = FakeGoogleOAuthClient(exchange_raises=GoogleAuthError("invalid_grant"))
    app = _build_app(session_factory, fake, email_spy)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await _round_trip(ac)

    assert _outcome(resp) == "exchange_failed"
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


async def test_userinfo_failure_is_reported(session_factory, db_session, email_spy):
    fake = FakeGoogleOAuthClient(identity_raises=GoogleApiError("userinfo 500"))
    app = _build_app(session_factory, fake, email_spy)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await _round_trip(ac)

    assert _outcome(resp) == "exchange_failed"


# --------------------------------------------------------------------------- #
# Capacity cap applies to Google sign-up too
# --------------------------------------------------------------------------- #


async def test_new_account_blocked_at_capacity(session_factory, db_session, fake_google, email_spy):
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_google_oauth_client] = lambda: fake_google
    app.dependency_overrides[get_email_sender] = lambda: email_spy
    # Cap of 1 — the seeded organizer already fills it (MYS-127).
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="development", app_base_url="https://app.example.test", max_users=1
    )
    invite_token = await _seed_club_invite(db_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await _round_trip(ac, invite_token)

    assert _outcome(resp) == "at_capacity"
    db_session.expire_all()
    assert await db_session.scalar(select(User).where(User.email == "newcomer@example.com")) is None


# --------------------------------------------------------------------------- #
# The state helper itself
# --------------------------------------------------------------------------- #


async def test_sign_in_state_round_trips_without_an_invite():
    from app.auth.jwt import decode_sign_in_state

    decoded = decode_sign_in_state(create_sign_in_state("nonce-1", "verifier-1"))

    assert decoded.nonce == "nonce-1"
    assert decoded.invite_token is None
    assert decoded.code_verifier == "verifier-1"


# --------------------------------------------------------------------------- #
# Per-IP rate limiting on the callback (MysteryMixClub-ali8.8)
# --------------------------------------------------------------------------- #


async def test_callback_rate_limits_by_ip_before_touching_state(google_client, db_session):
    """A flood of hits from one IP is throttled before any state/code
    processing -- proven by sending garbage state and getting "rate_limited"
    back rather than "invalid_state"."""
    from app.models.oauth_callback_attempt import OAuthCallbackAttempt

    ip = "9.9.9.9"
    now = datetime.now(timezone.utc)
    for _ in range(20):
        db_session.add(OAuthCallbackAttempt(ip=ip, created_at=now))
    await db_session.commit()

    resp = await google_client.get(
        CALLBACK_URL,
        params={"code": "auth-code", "state": "not-a-real-state"},
        headers={"X-Forwarded-For": ip},
    )

    assert _outcome(resp) == "rate_limited"


# --------------------------------------------------------------------------- #
# The nonce is one-shot: every exit from the callback consumes it
# --------------------------------------------------------------------------- #


def _clears_nonce(response) -> bool:
    """A delete_cookie shows up as a Set-Cookie for the name with an empty value."""
    return any(
        "google_oauth_nonce=" in header
        and ('google_oauth_nonce=""' in header or "Max-Age=0" in header)
        for header in response.headers.get_list("set-cookie")
    )


async def test_success_clears_the_nonce_cookie(google_client, db_session):
    invite_token = await _seed_club_invite(db_session)

    resp = await _round_trip(google_client, invite_token)

    assert _clears_nonce(resp), resp.headers.get_list("set-cookie")


async def test_rejection_also_clears_the_nonce_cookie(google_client, db_session):
    # Otherwise a nonce survives a failed attempt and authorizes a later one,
    # contradicting the whole point of binding it to a single flow.
    resp = await _round_trip(google_client)

    assert _outcome(resp) == "invite_required"
    assert _clears_nonce(resp), resp.headers.get_list("set-cookie")


async def test_a_consumed_nonce_cannot_be_replayed(google_client, db_session):
    # End-to-end: after one rejected callback the browser's cookie is gone, so
    # replaying the same state fails on the missing nonce.
    state = await _start_flow(google_client)
    first = await google_client.get(CALLBACK_URL, params={"code": "auth-code", "state": state})
    assert _outcome(first) == "invite_required"

    replay = await google_client.get(CALLBACK_URL, params={"code": "auth-code", "state": state})

    assert _outcome(replay) == "invalid_state"
