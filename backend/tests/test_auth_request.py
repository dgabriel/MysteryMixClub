"""Tests for MYS-6 + MYS-127: POST /api/v1/auth/request (magic link request).

Covers happy path, edge cases (email normalization, rate-limit boundary),
error states (invalid / missing email), and the v2 invite-gated sign-up gate
(MYS-127): a link is only mailed to an EXISTING (non-deleted) user or to someone
arriving through a valid unexpired invite link; everyone else gets the same
neutral response with no token persisted and no mail sent. See
technical-design.md §5, §6.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy import func, select

from app.auth.tokens import hash_token
from app.config import get_settings
from app.models.invite import Invite
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.magic_link_token import MagicLinkToken
from app.models.user import User

REQUEST_URL = "/api/v1/auth/request"
NEUTRAL_MESSAGE = "If that email is registered, a sign-in link is on its way."
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


# The happy-path / rate-limit tests below request links for bare addresses that,
# under v2 invite-gated sign-up (MYS-127), only receive a link if they already
# belong to an existing user. Seed those addresses as real accounts so the
# token-issuing path is exercised. The dedicated gate tests further down seed
# their own state to assert the gate itself.
_LEGACY_TEST_EMAILS = (
    "alice@example.com",
    "foo@x.com",
    "boundary@example.com",
    "busy@example.com",
    "fresh@example.com",
)


@pytest_asyncio.fixture(autouse=True)
async def _seed_legacy_users(session_factory):
    """Ensure the bare addresses used by the happy-path/rate-limit tests exist as
    accounts, so v2 /auth/request issues them a token."""
    async with session_factory() as db:
        for email in _LEGACY_TEST_EMAILS:
            if await db.scalar(select(User).where(User.email == email)) is None:
                db.add(User(email=email, display_name=""))
        await db.commit()


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
        # alice is an existing user (seeded by the autouse fixture), so the gate
        # lets the request through; the assertion is only about dev_token secrecy.
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


# --------------------------------------------------------------------------- #
# Invite-gated sign-up (MYS-127)
#
# A magic-link request is honored only if the email belongs to an existing
# (non-deleted) user, OR a valid unexpired invite_token is supplied. Otherwise
# the SAME neutral response is returned with NO token persisted and NO email
# sent — both anti-bot (no open sign-up) and anti-enumeration. A valid invite
# token rides through to /auth/verify on the link's &invite= so the new account
# is joined to that club.
# --------------------------------------------------------------------------- #


async def _seed_invite(db_session, *, expires_at: datetime | None) -> str:
    """Seed an organizer + club + shareable invite and return its token."""
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
    db_session.add(
        Invite(
            club_id=club.id,
            created_by=organizer.id,
            token=token,
            expires_at=expires_at,
        )
    )
    await db_session.commit()
    return token


async def test_existing_user_without_invite_issues_token(client, db_session, email_spy):
    # alice is seeded as an existing user; she signs in with no invite at all.
    resp = await client.post(REQUEST_URL, json={"email": "alice@example.com"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["dev_token"]
    assert await _count_rows(db_session, "alice@example.com") == 1
    assert email_spy.call_count == 1


async def test_new_email_without_invite_gets_neutral_no_token_no_email(
    client, db_session, email_spy
):
    # A brand-new address with no invite is the open-sign-up case the gate blocks.
    resp = await client.post(REQUEST_URL, json={"email": "stranger@example.com"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"] == NEUTRAL_MESSAGE
    assert "dev_token" not in body
    assert await _count_rows(db_session, "stranger@example.com") == 0
    assert email_spy.call_count == 0


async def test_new_email_with_valid_invite_issues_token_and_carries_invite(
    client, db_session, email_spy
):
    token = await _seed_invite(db_session, expires_at=None)

    resp = await client.post(
        REQUEST_URL, json={"email": "invitee@example.com", "invite_token": token}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["dev_token"]
    assert await _count_rows(db_session, "invitee@example.com") == 1
    assert email_spy.call_count == 1
    # The link carries the invite token through to verify so the new account is
    # joined to the club on sign-in.
    _, link = email_spy.calls[-1]
    assert f"&invite={token}" in link


async def test_new_email_with_unexpired_dated_invite_issues_token(client, db_session, email_spy):
    token = await _seed_invite(
        db_session, expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
    )

    resp = await client.post(
        REQUEST_URL, json={"email": "invitee@example.com", "invite_token": token}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["dev_token"]
    assert await _count_rows(db_session, "invitee@example.com") == 1


async def test_new_email_with_expired_invite_gets_neutral_no_token(client, db_session, email_spy):
    token = await _seed_invite(
        db_session, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
    )

    resp = await client.post(
        REQUEST_URL, json={"email": "invitee@example.com", "invite_token": token}
    )

    assert resp.status_code == 200, resp.text
    assert "dev_token" not in resp.json()
    assert await _count_rows(db_session, "invitee@example.com") == 0
    assert email_spy.call_count == 0


async def test_new_email_with_unknown_invite_token_gets_neutral_no_token(
    client, db_session, email_spy
):
    resp = await client.post(
        REQUEST_URL,
        json={"email": "invitee@example.com", "invite_token": "no-such-invite"},
    )

    assert resp.status_code == 200, resp.text
    assert "dev_token" not in resp.json()
    assert await _count_rows(db_session, "invitee@example.com") == 0
    assert email_spy.call_count == 0


async def test_soft_deleted_user_without_invite_gets_neutral(client, db_session, email_spy):
    # A soft-deleted account no longer counts as an existing user for the gate.
    db_session.add(
        User(
            email="ghost@example.com",
            display_name="Ghost",
            deleted_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    resp = await client.post(REQUEST_URL, json={"email": "ghost@example.com"})

    assert resp.status_code == 200, resp.text
    assert "dev_token" not in resp.json()
    assert await _count_rows(db_session, "ghost@example.com") == 0
    assert email_spy.call_count == 0


async def test_existing_user_link_omits_invite_when_no_token_supplied(
    client, db_session, email_spy
):
    # An existing user signing in without an invite token gets a plain link.
    resp = await client.post(REQUEST_URL, json={"email": "alice@example.com"})

    assert resp.status_code == 200, resp.text
    _, link = email_spy.calls[-1]
    assert "&invite=" not in link
