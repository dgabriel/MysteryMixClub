"""Tests for MYS-59: Secure flag on auth cookies in all HTTPS environments.

Covers:
- Unit-level on ``Settings.secure_cookies`` (no DB): development is False,
  staging and production are True.
- ``/auth/verify`` emits ``Secure`` on the refresh Set-Cookie when the request
  observes a non-dev environment (staging / production).
- ``/auth/verify`` does NOT emit ``Secure`` under the suite's default
  development environment.
- ``/auth/logout`` and ``/auth/logout-all`` clear the cookie WITH ``Secure``
  under a non-dev environment (the delete_cookie path must match the set path's
  security attributes so the cookie actually clears).

The Secure attribute is decided at request time from ``settings.secure_cookies``,
where ``settings`` is injected into each handler via ``Depends(get_settings)``.
To flip the environment for one request without touching the global lru_cached
``get_settings()`` (which would leak across tests), these tests build a dedicated
ASGI client and override the ``get_settings`` FastAPI dependency on that app
instance only. The override lives on a throwaway ``create_app()`` and is cleared
on fixture teardown, so it cannot bleed into the shared ``client`` fixture or
other test modules. See technical-design.md §5 (Security Rules) and §9.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.services.email import EmailSender, get_email_sender

REQUEST_URL = "/api/v1/auth/request"
VERIFY_URL = "/api/v1/auth/verify"
LOGOUT_URL = "/api/v1/auth/logout"
LOGOUT_ALL_URL = "/api/v1/auth/logout-all"


# --------------------------------------------------------------------------- #
# 1. Unit: Settings.secure_cookies property (no DB, no app)
# --------------------------------------------------------------------------- #


def test_secure_cookies_false_in_development():
    assert Settings(environment="development").secure_cookies is False


def test_secure_cookies_true_in_staging():
    assert Settings(environment="staging").secure_cookies is True


def test_secure_cookies_true_in_production():
    assert Settings(environment="production").secure_cookies is True


# Note: ``environment`` is typed Literal["development", "staging", "production"].
# Constructing Settings(environment="other") raises a pydantic ValidationError,
# so there is no reachable "unrecognized value" code path to assert on; the
# only non-Secure environment is "development". (Skipped per task guidance.)


# --------------------------------------------------------------------------- #
# Fixtures: a client whose injected settings observe a chosen environment.
# --------------------------------------------------------------------------- #


def _make_env_client_fixture(environment: str):
    """Build a client fixture bound to ``environment`` for the verify handler.

    Mirrors conftest's ``client`` fixture (overrides get_db + get_email_sender)
    but additionally overrides the ``get_settings`` dependency so the auth
    handlers see ``Settings(environment=...)`` for the duration of the request.
    The override lives on this throwaway app and is cleared on teardown, so it
    never touches the global lru_cached get_settings() or other tests.
    """

    @pytest_asyncio.fixture
    async def _fixture(session_factory, email_spy) -> AsyncGenerator[AsyncClient, None]:
        app = create_app()

        async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
            async with session_factory() as session:
                yield session

        def override_get_email_sender() -> EmailSender:
            return email_spy

        # Build the env-specific settings once. database_url/secret_key are
        # irrelevant here (db comes from the get_db override); only
        # ``environment`` -> ``secure_cookies`` is load-bearing.
        env_settings = Settings(environment=environment)

        def override_get_settings() -> Settings:
            return env_settings

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_email_sender] = override_get_email_sender
        app.dependency_overrides[get_settings] = override_get_settings

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

        # Teardown: drop every override (incl. get_settings) so nothing leaks.
        app.dependency_overrides.clear()

    return _fixture


staging_client = _make_env_client_fixture("staging")
production_client = _make_env_client_fixture("production")


async def _establish_session(client, email_spy, email: str) -> str:
    """request -> verify; return the raw refresh cookie value."""
    resp = await client.post(REQUEST_URL, json={"email": email})
    assert resp.status_code == 200, resp.text
    _, link = email_spy.calls[-1]
    raw = link.split("token=")[1]
    verify = await client.get(VERIFY_URL, params={"token": raw})
    assert verify.status_code == 200, verify.text
    cookie = verify.cookies.get("refresh_token")
    assert cookie, "verify did not set a refresh_token cookie"
    return cookie


# --------------------------------------------------------------------------- #
# 2. /auth/verify sets Secure in a non-dev environment
# --------------------------------------------------------------------------- #


async def test_verify_sets_secure_cookie_in_staging(staging_client, email_spy):
    resp = await staging_client.post(REQUEST_URL, json={"email": "alice@example.com"})
    assert resp.status_code == 200, resp.text
    _, link = email_spy.calls[-1]
    raw = link.split("token=")[1]

    verify = await staging_client.get(VERIFY_URL, params={"token": raw})

    assert verify.status_code == 200, verify.text
    set_cookie = verify.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie, set_cookie
    lowered = set_cookie.lower()
    # The whole point of MYS-59: Secure must be present outside development.
    assert "secure" in lowered, set_cookie
    # Other attributes still intact (regression guard on the set_cookie call).
    assert "httponly" in lowered, set_cookie
    # Lax (not Strict) so the session survives an OAuth-provider return (MYS-91).
    assert "samesite=lax" in lowered, set_cookie
    assert "path=/api/v1/auth" in lowered, set_cookie


async def test_verify_sets_secure_cookie_in_production(production_client, email_spy):
    resp = await production_client.post(REQUEST_URL, json={"email": "alice@example.com"})
    assert resp.status_code == 200, resp.text
    _, link = email_spy.calls[-1]
    raw = link.split("token=")[1]

    verify = await production_client.get(VERIFY_URL, params={"token": raw})

    assert verify.status_code == 200, verify.text
    lowered = verify.headers.get("set-cookie", "").lower()
    assert "secure" in lowered, verify.headers.get("set-cookie", "")


# --------------------------------------------------------------------------- #
# 3. /auth/verify does NOT set Secure under the default (development) env
# --------------------------------------------------------------------------- #


async def test_verify_does_not_set_secure_cookie_in_development(client, email_spy):
    # ``client`` is the shared conftest fixture: no get_settings override, so the
    # suite's default ENVIRONMENT=development is in force.
    resp = await client.post(REQUEST_URL, json={"email": "alice@example.com"})
    assert resp.status_code == 200, resp.text
    _, link = email_spy.calls[-1]
    raw = link.split("token=")[1]

    verify = await client.get(VERIFY_URL, params={"token": raw})

    assert verify.status_code == 200, verify.text
    set_cookie = verify.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie, set_cookie
    assert "secure" not in set_cookie.lower(), set_cookie


# --------------------------------------------------------------------------- #
# 4. logout / logout-all clear the cookie WITH Secure under a non-dev env
# --------------------------------------------------------------------------- #


def _assert_cookie_cleared(resp) -> None:
    """A logout Set-Cookie must clear refresh_token at the matching path."""
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie, set_cookie
    lowered = set_cookie.lower()
    assert "path=/api/v1/auth" in lowered, set_cookie
    cleared = "max-age=0" in lowered or "expires=" in lowered
    assert cleared, f"cookie not cleared: {set_cookie}"


async def test_logout_clears_cookie_with_secure_in_staging(staging_client, email_spy):
    raw_cookie = await _establish_session(staging_client, email_spy, "alice@example.com")

    resp = await staging_client.post(LOGOUT_URL, cookies={"refresh_token": raw_cookie})

    assert resp.status_code == 200, resp.text
    set_cookie = resp.headers.get("set-cookie", "")
    # delete_cookie must carry Secure so the clearing cookie matches the one set
    # in verify; otherwise the browser won't overwrite it and it never clears.
    assert "secure" in set_cookie.lower(), set_cookie
    _assert_cookie_cleared(resp)


async def test_logout_all_clears_cookie_with_secure_in_staging(staging_client, email_spy):
    raw_cookie = await _establish_session(staging_client, email_spy, "alice@example.com")

    resp = await staging_client.post(LOGOUT_ALL_URL, cookies={"refresh_token": raw_cookie})

    assert resp.status_code == 200, resp.text
    set_cookie = resp.headers.get("set-cookie", "")
    assert "secure" in set_cookie.lower(), set_cookie
    _assert_cookie_cleared(resp)


# A control: under development the logout clear cookie must NOT carry Secure
# (it has to match the non-Secure cookie set in dev).
async def test_logout_clears_cookie_without_secure_in_development(client, email_spy):
    raw_cookie = await _establish_session(client, email_spy, "alice@example.com")

    resp = await client.post(LOGOUT_URL, cookies={"refresh_token": raw_cookie})

    assert resp.status_code == 200, resp.text
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie, set_cookie
    assert "secure" not in set_cookie.lower(), set_cookie


# Defensive: constructing Settings with an invalid environment is rejected by
# pydantic, confirming "development" is the only path that yields secure=False.
def test_invalid_environment_is_rejected_by_validation():
    with pytest.raises(Exception):
        Settings(environment="qa")
