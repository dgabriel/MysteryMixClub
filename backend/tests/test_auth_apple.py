"""Tests for MysteryMixClub-4vii.9 (Guideline 4.8): Sign in with Apple.

Apple's real ASAuthorizationController can't be driven by an automated
backend test either (it's entirely client-side, unlike Google's server-to-
server code exchange) -- so these tests mint a real, self-signed RS256
identity token and exercise the actual verification code in
app.services.apple_signin against a ``FakeAppleJWKSClient`` standing in for
Apple's JWKS endpoint (no network). Signature verification, audience/issuer/
expiry checks, and account resolution are all real; only the network call to
fetch Apple's public keys is faked -- mirroring test_auth_google.py's
"exercise the real thing, fake the network" approach.

PKs are captured into locals before any expire_all (project MissingGreenlet
gotcha).
"""

import time
import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from jose import jwk as jose_jwk
from jose import jwt as jose_jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.models.auth_identity import AuthIdentity
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.invite import Invite
from app.models.session import Session
from app.models.user import User
from app.services.apple_signin import AppleJWKSClient, get_apple_jwks_client
from app.services.email import get_email_sender

VERIFY_URL = "/api/v1/auth/apple/native-verify"
ME_URL = "/api/v1/users/me"
BUNDLE_ID = "com.mysterymixclub.app"
APPLE_SUB = "apple-sub-0000000000.abcdef"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
_KID = "test-kid-1"
_PUBLIC_JWK = jose_jwk.construct(_PRIVATE_PEM, algorithm="RS256").to_dict()
_PUBLIC_JWK["kid"] = _KID
_PUBLIC_JWK["use"] = "sig"


def _identity_token(**claim_overrides) -> str:
    claims = {
        "iss": "https://appleid.apple.com",
        "aud": BUNDLE_ID,
        "sub": APPLE_SUB,
        "email": "newcomer@example.com",
        "email_verified": "true",
        "is_private_email": "false",
        "exp": int(time.time()) + 300,
    }
    claims.update(claim_overrides)
    return jose_jwt.encode(claims, _PRIVATE_PEM, algorithm="RS256", headers={"kid": _KID})


class FakeAppleJWKSClient(AppleJWKSClient):
    """Serves the test keypair's public JWK instead of calling Apple."""

    def __init__(self) -> None:
        super().__init__()
        self._cached_keys = {_KID: _PUBLIC_JWK}
        self._cached_at = time.monotonic()


async def _seed_user(db_session, email: str, **overrides) -> User:
    apple_id = overrides.pop("apple_id", None)
    user = User(email=email, display_name="", **overrides)
    db_session.add(user)
    await db_session.flush()
    if apple_id is not None:
        db_session.add(AuthIdentity(user_id=user.id, provider="apple", subject=apple_id))
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


def _build_app(session_factory, email_spy, *, settings: Settings | None = None):
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_apple_jwks_client] = lambda: FakeAppleJWKSClient()
    app.dependency_overrides[get_email_sender] = lambda: email_spy
    app.dependency_overrides[get_settings] = lambda: (
        settings or Settings(environment="development", app_base_url="https://app.example.test")
    )
    return app


@pytest_asyncio.fixture
async def apple_client(session_factory, email_spy) -> AsyncGenerator[AsyncClient, None]:
    app = _build_app(session_factory, email_spy)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Brand-new account (invite-gated)
# --------------------------------------------------------------------------- #


async def test_new_signup_creates_an_account_and_a_session(apple_client, db_session):
    invite_token = await _seed_club_invite(db_session)

    resp = await apple_client.post(
        VERIFY_URL, json={"identity_token": _identity_token(), "invite_token": invite_token}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]
    assert resp.cookies.get("refresh_token")
    db_session.expire_all()
    user = await db_session.scalar(select(User).where(User.email == "newcomer@example.com"))
    assert user is not None
    identity = await db_session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "apple", AuthIdentity.subject == APPLE_SUB
        )
    )
    assert identity is not None
    assert identity.user_id == user.id


async def test_new_signup_without_an_invite_is_rejected(apple_client, db_session):
    resp = await apple_client.post(VERIFY_URL, json={"identity_token": _identity_token()})

    assert resp.status_code == 403, resp.text
    assert "invite" in resp.json()["detail"].lower()
    db_session.expire_all()
    assert await db_session.scalar(select(User).where(User.email == "newcomer@example.com")) is None


async def test_at_capacity_signup_is_rejected(session_factory, db_session, email_spy):
    app = _build_app(
        session_factory,
        email_spy,
        settings=Settings(
            environment="development", app_base_url="https://app.example.test", max_users=1
        ),
    )
    invite_token = await _seed_club_invite(db_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            VERIFY_URL, json={"identity_token": _identity_token(), "invite_token": invite_token}
        )

    assert resp.status_code == 403, resp.text
    db_session.expire_all()
    assert await db_session.scalar(select(User).where(User.email == "newcomer@example.com")) is None


# --------------------------------------------------------------------------- #
# Already linked -- straight sign-in
# --------------------------------------------------------------------------- #


async def test_already_linked_subject_signs_in(apple_client, db_session):
    user = await _seed_user(db_session, "someone@example.com", apple_id=APPLE_SUB)
    user_id = user.id

    resp = await apple_client.post(
        VERIFY_URL, json={"identity_token": _identity_token(email="someone@example.com")}
    )

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    session_row = await db_session.scalar(select(Session).where(Session.user_id == user_id))
    assert session_row is not None


# --------------------------------------------------------------------------- #
# Existing account, matched by a real (non-relay) verified email
# --------------------------------------------------------------------------- #


async def test_real_email_links_onto_an_existing_account_without_an_invite(
    apple_client, db_session
):
    user = await _seed_user(db_session, "newcomer@example.com")
    user_id = user.id

    resp = await apple_client.post(VERIFY_URL, json={"identity_token": _identity_token()})

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    identity = await db_session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.user_id == user_id, AuthIdentity.provider == "apple"
        )
    )
    assert identity is not None
    assert identity.subject == APPLE_SUB


# --------------------------------------------------------------------------- #
# Private relay email -- identity-conflict hardening (MysteryMixClub-4vii.9)
# --------------------------------------------------------------------------- #


async def test_private_relay_email_never_auto_links_an_existing_account(apple_client, db_session):
    # A relay address is real and Apple-verified, but proves nothing about who
    # owns any *other* mailbox -- unlike a real Google/Apple email, it must
    # never silently attach to an unrelated existing account. Since
    # users.email is unique, the only safe outcome is a clean conflict, not a
    # crash and not a silent link.
    existing = await _seed_user(db_session, "relay-collision@example.com")
    existing_id = existing.id
    invite_token = await _seed_club_invite(db_session)

    resp = await apple_client.post(
        VERIFY_URL,
        json={
            "identity_token": _identity_token(
                email="relay-collision@example.com", is_private_email="true"
            ),
            "invite_token": invite_token,
        },
    )

    assert resp.status_code == 409, resp.text
    db_session.expire_all()
    # Nothing was linked or created off the back of this request.
    assert (
        await db_session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == "apple", AuthIdentity.subject == APPLE_SUB
            )
        )
        is None
    )
    only_match = await db_session.scalar(
        select(User).where(User.email == "relay-collision@example.com")
    )
    assert only_match.id == existing_id


async def test_private_relay_email_signup_is_still_invite_gated(apple_client, db_session):
    # No existing account with this email at all -- a genuine brand-new
    # signup, which is invite-gated exactly like any other (ADR 0007),
    # relay email or not.
    resp = await apple_client.post(
        VERIFY_URL,
        json={
            "identity_token": _identity_token(email="newcomer@example.com", is_private_email="true")
        },
    )

    assert resp.status_code == 403, resp.text
    assert "invite" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# Token verification failures
# --------------------------------------------------------------------------- #


async def test_unverified_email_is_rejected(apple_client, db_session):
    resp = await apple_client.post(
        VERIFY_URL, json={"identity_token": _identity_token(email_verified="false")}
    )

    assert resp.status_code == 401, resp.text
    db_session.expire_all()
    assert await db_session.scalar(select(User).where(User.email == "newcomer@example.com")) is None


async def test_wrong_audience_is_rejected(apple_client):
    resp = await apple_client.post(
        VERIFY_URL, json={"identity_token": _identity_token(aud="com.someoneelse.app")}
    )

    assert resp.status_code == 401, resp.text


async def test_wrong_issuer_is_rejected(apple_client):
    resp = await apple_client.post(
        VERIFY_URL, json={"identity_token": _identity_token(iss="https://evil.example.com")}
    )

    assert resp.status_code == 401, resp.text


async def test_expired_token_is_rejected(apple_client):
    resp = await apple_client.post(
        VERIFY_URL, json={"identity_token": _identity_token(exp=int(time.time()) - 60)}
    )

    assert resp.status_code == 401, resp.text


async def test_malformed_token_is_rejected(apple_client):
    resp = await apple_client.post(VERIFY_URL, json={"identity_token": "not-a-jwt"})

    assert resp.status_code == 401, resp.text


async def test_signature_from_a_different_key_is_rejected(apple_client):
    forged_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged_pem = forged_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    forged_token = jose_jwt.encode(
        {
            "iss": "https://appleid.apple.com",
            "aud": BUNDLE_ID,
            "sub": APPLE_SUB,
            "email": "newcomer@example.com",
            "email_verified": "true",
            "exp": int(time.time()) + 300,
        },
        forged_pem,
        algorithm="RS256",
        # Same kid as the real key, so verification must catch the signature
        # mismatch itself rather than merely failing to find a key.
        headers={"kid": _KID},
    )

    resp = await apple_client.post(VERIFY_URL, json={"identity_token": forged_token})

    assert resp.status_code == 401, resp.text


# --------------------------------------------------------------------------- #
# Profile + account deletion
# --------------------------------------------------------------------------- #


async def test_profile_reflects_apple_linked_after_sign_in(apple_client, db_session):
    invite_token = await _seed_club_invite(db_session)
    resp = await apple_client.post(
        VERIFY_URL, json={"identity_token": _identity_token(), "invite_token": invite_token}
    )
    access_token = resp.json()["access_token"]

    me = await apple_client.get(ME_URL, headers={"Authorization": f"Bearer {access_token}"})

    assert me.status_code == 200, me.text
    assert me.json()["apple_linked"] is True
    assert me.json()["google_linked"] is False


async def test_account_deletion_clears_the_apple_identity(apple_client, db_session):
    invite_token = await _seed_club_invite(db_session)
    await apple_client.post(
        VERIFY_URL, json={"identity_token": _identity_token(), "invite_token": invite_token}
    )
    user = await db_session.scalar(select(User).where(User.email == "newcomer@example.com"))
    user_id = user.id

    resp = await apple_client.delete(
        ME_URL, headers={"Authorization": f"Bearer {create_access_token(user_id)}"}
    )

    assert resp.status_code == 204, resp.text
    db_session.expire_all()
    identity = await db_session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "apple", AuthIdentity.subject == APPLE_SUB
        )
    )
    assert identity is None
