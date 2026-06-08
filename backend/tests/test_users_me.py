"""Tests for MYS-26: get_current_user Bearer dependency + GET/PATCH /users/me.

Covers the auth dependency (exercised via GET /users/me): valid token, missing
header, garbage token, expired token, well-formed-UUID-but-no-user, and
soft-deleted user. Then GET /users/me response shape, PATCH happy/partial paths,
validation rejections, and the explicit-null edge case against the NOT NULL
columns. See technical-design.md §5 (auth) and §6 (users data model).
"""

import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.config import get_settings
from app.models.user import User

ME_URL = "/api/v1/users/me"
_JWT_ALGORITHM = "HS256"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, **overrides) -> User:
    """Insert and commit a User, returning it. display_name is NOT NULL."""
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


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _expired_token(user_id: uuid.UUID) -> str:
    """Mint a structurally valid JWT whose exp is in the past."""
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    claims = {
        "sub": str(user_id),
        "iat": int((past - timedelta(minutes=60)).timestamp()),
        "exp": int(past.timestamp()),
    }
    return jwt.encode(claims, get_settings().secret_key, algorithm=_JWT_ALGORITHM)


# --------------------------------------------------------------------------- #
# Auth dependency (exercised via GET /users/me)
# --------------------------------------------------------------------------- #


async def test_valid_token_returns_200_and_profile(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.get(ME_URL, headers=_auth_header(user.id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "Alice"
    assert body["email"] == "alice@example.com"


async def test_missing_authorization_header_returns_401(client):
    resp = await client.get(ME_URL)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


async def test_garbage_token_returns_401(client):
    resp = await client.get(ME_URL, headers={"Authorization": "Bearer not-a-jwt"})

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


async def test_expired_token_returns_401(client, db_session):
    user = await _seed_user(db_session)
    token = _expired_token(user.id)

    resp = await client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


async def test_token_for_nonexistent_user_returns_401(client, db_session):
    # Well-formed UUID sub, but no such user row exists.
    token = create_access_token(uuid.uuid4())

    resp = await client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


async def test_soft_deleted_user_returns_401(client, db_session):
    user = await _seed_user(db_session, deleted_at=datetime.now(timezone.utc) - timedelta(days=1))

    resp = await client.get(ME_URL, headers=_auth_header(user.id))

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "not authenticated"


# --------------------------------------------------------------------------- #
# GET /users/me
# --------------------------------------------------------------------------- #


async def test_get_me_returns_exact_profile_shape(client, db_session):
    user = await _seed_user(
        db_session,
        email="bob@example.com",
        display_name="Bob",
        preferred_service=None,
        default_vibe_mode=True,
    )

    resp = await client.get(ME_URL, headers=_auth_header(user.id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {
        "display_name",
        "email",
        "preferred_service",
        "default_vibe_mode",
    }
    assert body["display_name"] == "Bob"
    assert body["email"] == "bob@example.com"
    assert body["preferred_service"] is None
    assert body["default_vibe_mode"] is True


# --------------------------------------------------------------------------- #
# PATCH /users/me — happy path
# --------------------------------------------------------------------------- #


async def test_patch_updates_all_fields_and_persists(client, db_session):
    user = await _seed_user(
        db_session,
        display_name="Alice",
        preferred_service=None,
        default_vibe_mode=False,
    )
    user_id = user.id

    resp = await client.patch(
        ME_URL,
        headers=_auth_header(user_id),
        json={
            "display_name": "  Alice Cooper  ",
            "preferred_service": "spotify",
            "default_vibe_mode": True,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # display_name is trimmed by StringConstraints(strip_whitespace=True).
    assert body["display_name"] == "Alice Cooper"
    assert body["preferred_service"] == "spotify"
    assert body["default_vibe_mode"] is True

    db_session.expire_all()
    fresh = await db_session.scalar(select(User).where(User.id == user_id))
    assert fresh.display_name == "Alice Cooper"
    assert fresh.preferred_service == "spotify"
    assert fresh.default_vibe_mode is True


async def test_patch_partial_leaves_omitted_fields_untouched(client, db_session):
    user = await _seed_user(
        db_session,
        display_name="Original Name",
        preferred_service="deezer",
        default_vibe_mode=True,
    )
    user_id = user.id

    resp = await client.patch(
        ME_URL,
        headers=_auth_header(user_id),
        json={"display_name": "New Name"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "New Name"
    # Omitted fields unchanged.
    assert body["preferred_service"] == "deezer"
    assert body["default_vibe_mode"] is True

    db_session.expire_all()
    fresh = await db_session.scalar(select(User).where(User.id == user_id))
    assert fresh.display_name == "New Name"
    assert fresh.preferred_service == "deezer"
    assert fresh.default_vibe_mode is True


# --------------------------------------------------------------------------- #
# PATCH /users/me — validation rejections (422)
# --------------------------------------------------------------------------- #


async def test_patch_empty_display_name_returns_422(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.patch(ME_URL, headers=_auth_header(user.id), json={"display_name": ""})

    assert resp.status_code == 422, resp.text


async def test_patch_whitespace_only_display_name_returns_422(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.patch(ME_URL, headers=_auth_header(user.id), json={"display_name": "   "})

    assert resp.status_code == 422, resp.text


async def test_patch_display_name_too_long_returns_422(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.patch(
        ME_URL, headers=_auth_header(user.id), json={"display_name": "x" * 51}
    )

    assert resp.status_code == 422, resp.text


async def test_patch_invalid_preferred_service_returns_422(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.patch(
        ME_URL,
        headers=_auth_header(user.id),
        json={"preferred_service": "applemusic"},
    )

    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- #
# PATCH /users/me — explicit-null edge case (NOT NULL columns)
# --------------------------------------------------------------------------- #


# display_name and default_vibe_mode map to NOT NULL columns. UserProfileUpdate's
# `_reject_explicit_null` model_validator rejects an explicitly provided JSON null
# for these fields with a 422 (omission is still allowed for partial updates).
# preferred_service is nullable, so an explicit null is accepted.


async def test_patch_explicit_null_display_name_returns_422(client, db_session):
    """Explicit null on NOT NULL display_name is rejected with 422."""
    user = await _seed_user(db_session)

    resp = await client.patch(ME_URL, headers=_auth_header(user.id), json={"display_name": None})

    assert resp.status_code == 422


async def test_patch_explicit_null_default_vibe_mode_returns_422(client, db_session):
    """Explicit null on NOT NULL default_vibe_mode is rejected with 422."""
    user = await _seed_user(db_session)

    resp = await client.patch(
        ME_URL, headers=_auth_header(user.id), json={"default_vibe_mode": None}
    )

    assert resp.status_code == 422


async def test_patch_explicit_null_preferred_service_returns_200(client, db_session):
    """preferred_service is nullable: explicit null is accepted and clears it."""
    user = await _seed_user(db_session, preferred_service="spotify")
    user_id = user.id

    resp = await client.patch(
        ME_URL, headers=_auth_header(user_id), json={"preferred_service": None}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["preferred_service"] is None

    db_session.expire_all()
    fresh = await db_session.scalar(select(User).where(User.id == user_id))
    assert fresh.preferred_service is None
