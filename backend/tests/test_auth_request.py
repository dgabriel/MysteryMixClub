"""Tests for MYS-6: POST /api/v1/auth/request (magic link request endpoint).

Covers happy path, edge cases (email normalization, rate-limit boundary),
and error states (invalid / missing email). See technical-design.md §5, §6.
"""

import re
from datetime import timedelta

from sqlalchemy import func, select

from app.auth.tokens import hash_token
from app.config import get_settings
from app.models.magic_link_token import MagicLinkToken

REQUEST_URL = "/api/v1/auth/request"
NEUTRAL_MESSAGE = "If that email is registered, a sign-in link is on its way."
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


async def _count_rows(db_session, email: str | None = None) -> int:
    stmt = select(func.count()).select_from(MagicLinkToken)
    if email is not None:
        stmt = stmt.where(MagicLinkToken.email == email)
    return await db_session.scalar(stmt)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


async def test_valid_email_returns_200_neutral_message(client, email_spy):
    resp = await client.post(REQUEST_URL, json={"email": "alice@example.com"})

    assert resp.status_code == 200
    assert resp.json()["message"] == NEUTRAL_MESSAGE


async def test_dev_token_returned_outside_production(client, email_spy):
    # Tests run with environment != "production", so the raw token is handed back
    # for dev/staging UIs. It must match the link the email sender received.
    resp = await client.post(REQUEST_URL, json={"email": "alice@example.com"})

    assert resp.status_code == 200
    dev_token = resp.json()["dev_token"]
    assert dev_token
    assert email_spy.calls[0][1].endswith(f"/auth/verify?token={dev_token}")


async def test_dev_token_absent_in_production(session_factory, email_spy):
    # In production the token must never be exposed in the response body.
    from httpx import ASGITransport, AsyncClient

    from app.config import Settings, get_settings
    from app.db.session import get_db
    from app.main import create_app
    from app.services.email import get_email_sender

    app = create_app()

    async def _override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_email_sender] = lambda: email_spy
    app.dependency_overrides[get_settings] = lambda: Settings(environment="production")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(REQUEST_URL, json={"email": "alice@example.com"})

    assert resp.status_code == 200
    assert "dev_token" not in resp.json()


async def test_valid_email_inserts_exactly_one_row(client, db_session):
    await client.post(REQUEST_URL, json={"email": "alice@example.com"})

    assert await _count_rows(db_session) == 1


async def test_stored_token_hash_is_sha256_and_raw_not_stored(client, db_session, email_spy):
    await client.post(REQUEST_URL, json={"email": "alice@example.com"})

    row = (await db_session.execute(select(MagicLinkToken))).scalar_one()

    # token_hash is a 64-char sha256 hex digest.
    assert SHA256_HEX.match(row.token_hash), f"not a sha256 hex: {row.token_hash!r}"

    # The raw token sent in the email link must NOT be the stored value.
    _, link = email_spy.calls[0]
    raw_token = link.split("token=")[1]
    assert row.token_hash != raw_token
    # And the stored hash must be the hash of the raw token.
    assert row.token_hash == hash_token(raw_token)


async def test_expiry_is_created_at_plus_15_minutes_and_unused(client, db_session):
    await client.post(REQUEST_URL, json={"email": "alice@example.com"})

    row = (await db_session.execute(select(MagicLinkToken))).scalar_one()

    assert row.used is False
    delta = row.expires_at - row.created_at
    # Allow a small skew for clock/server-default timing.
    assert abs(delta - timedelta(minutes=15)) < timedelta(seconds=5), (
        f"expected ~15 min between created_at and expires_at, got {delta}"
    )


async def test_email_sender_called_once_with_email_and_link(client, email_spy):
    settings = get_settings()
    await client.post(REQUEST_URL, json={"email": "alice@example.com"})

    assert email_spy.call_count == 1
    sent_email, link = email_spy.calls[0]
    assert sent_email == "alice@example.com"
    assert "token=" in link
    assert link.startswith(settings.app_base_url.rstrip("/"))
    # Link carries a non-empty token.
    assert link.split("token=")[1] != ""


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #


async def test_email_normalized_to_lowercase_in_storage(client, db_session, email_spy):
    await client.post(REQUEST_URL, json={"email": "Alice@Example.COM"})

    row = (await db_session.execute(select(MagicLinkToken))).scalar_one()
    assert row.email == "alice@example.com"
    # Sender also receives the normalized address.
    assert email_spy.calls[0][0] == "alice@example.com"


async def test_rate_limit_is_case_insensitive_shared_bucket(client, db_session):
    # 3 mixed-case + 2 lowercase = 5 toward the same bucket; 6th should 429.
    casings = [
        "FOO@x.com",
        "foo@x.com",
        "Foo@X.com",
        "foo@x.COM",
        "fOo@x.com",
    ]
    for addr in casings:
        r = await client.post(REQUEST_URL, json={"email": addr})
        assert r.status_code == 200, f"{addr} -> {r.status_code}"

    sixth = await client.post(REQUEST_URL, json={"email": "foo@x.com"})
    assert sixth.status_code == 429

    # All five normalized to the same bucket, sixth created nothing.
    assert await _count_rows(db_session, "foo@x.com") == 5
    assert await _count_rows(db_session) == 5


async def test_rate_limit_boundary_five_ok_sixth_429(client, db_session):
    email = "boundary@example.com"

    for i in range(5):
        r = await client.post(REQUEST_URL, json={"email": email})
        assert r.status_code == 200, f"request {i + 1} -> {r.status_code}"

    assert await _count_rows(db_session, email) == 5

    sixth = await client.post(REQUEST_URL, json={"email": email})
    assert sixth.status_code == 429

    # The 6th must NOT have created an additional row.
    assert await _count_rows(db_session, email) == 5


async def test_rate_limit_is_per_email_not_global(client, db_session):
    # Exhaust one email's bucket, a different email is unaffected.
    for _ in range(5):
        await client.post(REQUEST_URL, json={"email": "busy@example.com"})
    blocked = await client.post(REQUEST_URL, json={"email": "busy@example.com"})
    assert blocked.status_code == 429

    other = await client.post(REQUEST_URL, json={"email": "fresh@example.com"})
    assert other.status_code == 200
    assert await _count_rows(db_session, "fresh@example.com") == 1


# --------------------------------------------------------------------------- #
# Error states
# --------------------------------------------------------------------------- #


async def test_invalid_email_returns_422_no_row(client, db_session):
    resp = await client.post(REQUEST_URL, json={"email": "notanemail"})

    assert resp.status_code == 422
    assert await _count_rows(db_session) == 0


async def test_missing_email_field_returns_422(client, db_session):
    resp = await client.post(REQUEST_URL, json={})

    assert resp.status_code == 422
    assert await _count_rows(db_session) == 0


async def test_empty_body_returns_422(client, db_session):
    resp = await client.post(REQUEST_URL, content=b"")

    assert resp.status_code == 422
    assert await _count_rows(db_session) == 0


async def test_empty_email_string_returns_422(client, db_session):
    resp = await client.post(REQUEST_URL, json={"email": ""})

    assert resp.status_code == 422
    assert await _count_rows(db_session) == 0


async def test_no_email_sent_on_validation_error(client, email_spy):
    await client.post(REQUEST_URL, json={"email": "notanemail"})
    assert email_spy.call_count == 0


# --------------------------------------------------------------------------- #
# Email delivery failure must not take down sign-in (the token is already
# persisted; outside production the dev_token still lets the UI sign in).
# --------------------------------------------------------------------------- #


class _FailingEmailSender:
    """Email sender that always raises, simulating an unverified-domain / outage."""

    def send_magic_link(self, email: str, link: str) -> None:
        raise RuntimeError("domain is not verified")

    def send(self, email, subject, html, headers=None) -> None:
        raise RuntimeError("domain is not verified")


async def _client_with_failing_email(session_factory, environment: str):
    from httpx import ASGITransport, AsyncClient

    from app.config import Settings, get_settings
    from app.db.session import get_db
    from app.main import create_app
    from app.services.email import get_email_sender

    app = create_app()

    async def _override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_email_sender] = lambda: _FailingEmailSender()
    app.dependency_overrides[get_settings] = lambda: Settings(environment=environment)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_send_failure_outside_production_still_succeeds_with_dev_token(
    session_factory, db_session
):
    async with await _client_with_failing_email(session_factory, "staging") as ac:
        resp = await ac.post(REQUEST_URL, json={"email": "alice@example.com"})

    # Delivery failed, but sign-in is not blocked: 200 + a usable dev_token.
    assert resp.status_code == 200
    assert resp.json()["dev_token"]
    # The token row was still persisted (it is created before the send).
    assert await _count_rows(db_session, "alice@example.com") == 1


async def test_send_failure_in_production_returns_502(session_factory, db_session):
    async with await _client_with_failing_email(session_factory, "production") as ac:
        resp = await ac.post(REQUEST_URL, json={"email": "alice@example.com"})

    # In production email is the only way in, so surface a clean 502 (not a raw 500).
    assert resp.status_code == 502
    assert "dev_token" not in resp.json()
