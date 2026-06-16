"""MYS-57 — Security response headers middleware (API).

`SecurityHeadersMiddleware` (app/middleware/security_headers.py, registered in
`create_app`) sets four static security headers on every response, plus an
HSTS header that is emitted **only** when `settings.environment == "production"`.

Covers:
- the four non-HSTS headers are present with exact values on a normal 200,
- HSTS is absent under the default/dev environment,
- HSTS is present with its exact value when the production branch is exercised,
- all four non-HSTS headers also wrap error responses (404 / 401).

The middleware reads `get_settings()` at request time via the name imported into
`app.middleware.security_headers`, so the production branch is flipped by
monkeypatching that reference to return a production `Settings`. A fixture
restores the original afterward so no production state leaks into other tests.
The `client` fixture (conftest) is an httpx AsyncClient over the ASGI app, which
runs the full middleware stack including the security-headers middleware.
"""

import app.middleware.security_headers as security_headers_module
from app.config import Settings

HEALTHZ_URL = "/api/v1/healthz"

# Exact header name -> value contract the middleware must emit on every response.
EXPECTED_STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}

EXPECTED_HSTS_VALUE = "max-age=63072000; includeSubDomains"


def _assert_static_headers(headers) -> None:
    for name, value in EXPECTED_STATIC_HEADERS.items():
        assert headers.get(name) == value, f"{name} expected {value!r}, got {headers.get(name)!r}"


# --------------------------------------------------------------------------- #
# Non-HSTS headers on a normal response
# --------------------------------------------------------------------------- #


async def test_static_security_headers_present_on_normal_response(client):
    resp = await client.get(HEALTHZ_URL)

    assert resp.status_code == 200, resp.text
    _assert_static_headers(resp.headers)


# --------------------------------------------------------------------------- #
# HSTS absent in development (default environment)
# --------------------------------------------------------------------------- #


async def test_hsts_absent_in_development(client):
    # The suite runs with ENVIRONMENT=development, so the production branch is
    # not taken and HSTS must not be emitted.
    resp = await client.get(HEALTHZ_URL)

    assert resp.status_code == 200, resp.text
    assert "Strict-Transport-Security" not in resp.headers, (
        "HSTS must not be emitted outside production"
    )


# --------------------------------------------------------------------------- #
# HSTS present in production
# --------------------------------------------------------------------------- #


async def test_hsts_present_in_production(client, monkeypatch):
    # The middleware calls the `get_settings` name imported into its own module
    # at request time. Override that name to return production settings, then
    # let monkeypatch's teardown restore the real one so nothing leaks. The
    # lru_cache on the real get_settings is never touched/populated here.
    prod_settings = Settings(environment="production", _env_file=None)
    monkeypatch.setattr(security_headers_module, "get_settings", lambda: prod_settings)

    resp = await client.get(HEALTHZ_URL)

    assert resp.status_code == 200, resp.text
    assert resp.headers.get("Strict-Transport-Security") == EXPECTED_HSTS_VALUE
    # The static headers are still emitted alongside HSTS in production.
    _assert_static_headers(resp.headers)


# --------------------------------------------------------------------------- #
# Headers also wrap error responses
# --------------------------------------------------------------------------- #


async def test_static_headers_present_on_404(client):
    resp = await client.get("/api/v1/this-route-does-not-exist")

    assert resp.status_code == 404, resp.text
    _assert_static_headers(resp.headers)


async def test_static_headers_present_on_401(client):
    # logout-all requires a valid refresh cookie; with none it returns 401.
    resp = await client.post("/api/v1/auth/logout-all")

    assert resp.status_code == 401, resp.text
    _assert_static_headers(resp.headers)
