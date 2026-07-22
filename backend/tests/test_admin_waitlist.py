"""Tests for MYS-215: admin-side waitlist management.

Covers:
  GET  /api/v1/admin/waitlist              — list, platform-admin only
  POST /api/v1/admin/waitlist/{id}/invite  — mint + email a platform invite,
                                              stamp invited_at/invited_by,
                                              resendable

Public join flow is covered in test_waitlist.py. This mints the same
club-less Invite row shape POST /admin/invites creates (test_invites_admin.py)
— nothing about that existing flow changes — but with `email` locked to the
entry's address (MYS-215); email-lock enforcement itself is covered in
test_auth_request.py / test_auth_verify.py.
"""

import uuid

import pytest
from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.invite import Invite
from app.models.user import User
from app.models.waitlist_entry import WaitlistEntry

ADMIN_EMAIL = "admin@example.com"
LIST_URL = "/api/v1/admin/waitlist"


@pytest.fixture
def seed_admin_emails() -> str:
    return ADMIN_EMAIL


async def _seed_user(db_session, email: str, **overrides) -> User:
    defaults = {"email": email, "display_name": "U"}
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_admin(db_session) -> User:
    return await _seed_user(db_session, ADMIN_EMAIL, display_name="Admin")


async def _seed_entry(db_session, email: str, **overrides) -> WaitlistEntry:
    defaults = {"email": email}
    defaults.update(overrides)
    entry = WaitlistEntry(**defaults)
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)
    return entry


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _invite_url(entry_id) -> str:
    return f"/api/v1/admin/waitlist/{entry_id}/invite"


# --------------------------------------------------------------------------- #
# GET /admin/waitlist — list
# --------------------------------------------------------------------------- #


async def test_list_requires_auth(client):
    resp = await client.get(LIST_URL)
    assert resp.status_code == 401


async def test_list_non_admin_forbidden(client, db_session):
    user = await _seed_user(db_session, "u@example.com")
    resp = await client.get(LIST_URL, headers=_auth(user.id))
    assert resp.status_code == 403


async def test_list_returns_entries_oldest_first(client, db_session):
    admin = await _seed_admin(db_session)
    await _seed_entry(db_session, "second@example.com")
    await _seed_entry(db_session, "first@example.com")

    resp = await client.get(LIST_URL, headers=_auth(admin.id))
    assert resp.status_code == 200, resp.text
    emails = [row["email"] for row in resp.json()]
    assert emails == ["second@example.com", "first@example.com"]


async def test_list_shows_invited_state(client, db_session):
    admin = await _seed_admin(db_session)
    await _seed_entry(db_session, "pending@example.com")

    resp = await client.get(LIST_URL, headers=_auth(admin.id))
    row = resp.json()[0]
    assert row["invited_at"] is None
    assert row["invited_by"] is None


# --------------------------------------------------------------------------- #
# POST /admin/waitlist/{id}/invite
# --------------------------------------------------------------------------- #


async def test_invite_requires_auth(client, db_session):
    entry = await _seed_entry(db_session, "x@example.com")
    resp = await client.post(_invite_url(entry.id))
    assert resp.status_code == 401


async def test_invite_non_admin_forbidden(client, db_session):
    user = await _seed_user(db_session, "u@example.com")
    entry = await _seed_entry(db_session, "x@example.com")
    resp = await client.post(_invite_url(entry.id), headers=_auth(user.id))
    assert resp.status_code == 403


async def test_invite_unknown_entry_404(client, db_session):
    admin = await _seed_admin(db_session)
    resp = await client.post(_invite_url(uuid.uuid4()), headers=_auth(admin.id))
    assert resp.status_code == 404


async def test_invite_mints_a_clubless_invite_and_emails_it(client, db_session, email_spy):
    admin = await _seed_admin(db_session)
    entry = await _seed_entry(db_session, "waiting@example.com")
    admin_id, entry_id = admin.id, entry.id  # captured before expire_all() below

    resp = await client.post(_invite_url(entry_id), headers=_auth(admin_id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["invited_at"] is not None
    assert body["invited_by"] == str(admin_id)

    db_session.expire_all()
    entry_after = await db_session.get(WaitlistEntry, entry_id)
    assert entry_after.invited_at is not None
    assert entry_after.invited_by == admin_id

    invites = (await db_session.scalars(select(Invite).where(Invite.created_by == admin_id))).all()
    assert len(invites) == 1
    assert invites[0].club_id is None  # same club-less shape as POST /admin/invites
    assert invites[0].email == "waiting@example.com"  # locked to this entry (MYS-215)

    assert len(email_spy.sends) == 1
    to, _subject, html = email_spy.sends[0]
    assert to == "waiting@example.com"
    assert invites[0].token in html


class _FailingEmailSender:
    """Email sender that always raises, simulating an unverified-domain / outage
    (same shape as test_auth_request.py's twin)."""

    def send_magic_link(self, email: str, link: str) -> None:
        raise RuntimeError("domain is not verified")

    def send(self, email, subject, html, headers=None) -> None:
        raise RuntimeError("domain is not verified")


async def test_invite_send_failure_returns_502_and_persists_nothing(session_factory, db_session):
    # The email is the only way the recipient learns their invite exists, so a
    # delivery failure must not leave the entry marked "invited" with no
    # actual invite behind it.
    from httpx import ASGITransport, AsyncClient

    from app.config import Settings, get_settings
    from app.db.session import get_db
    from app.main import create_app
    from app.services.email import get_email_sender

    admin = await _seed_admin(db_session)
    entry = await _seed_entry(db_session, "waiting@example.com")
    admin_id, entry_id = admin.id, entry.id  # captured before expire_all() below

    app = create_app()

    async def _override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_email_sender] = lambda: _FailingEmailSender()
    app.dependency_overrides[get_settings] = lambda: Settings(seed_admin_emails=ADMIN_EMAIL)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(_invite_url(entry_id), headers=_auth(admin_id))

    assert resp.status_code == 502, resp.text

    db_session.expire_all()
    entry_after = await db_session.get(WaitlistEntry, entry_id)
    assert entry_after.invited_at is None
    assert entry_after.invited_by is None

    invites = (await db_session.scalars(select(Invite).where(Invite.created_by == admin_id))).all()
    assert len(invites) == 0


async def test_invite_is_resendable_and_mints_a_fresh_invite(client, db_session, email_spy):
    admin = await _seed_admin(db_session)
    entry = await _seed_entry(db_session, "waiting@example.com")

    first = await client.post(_invite_url(entry.id), headers=_auth(admin.id))
    assert first.status_code == 200, first.text
    first_invited_at = first.json()["invited_at"]

    second = await client.post(_invite_url(entry.id), headers=_auth(admin.id))
    assert second.status_code == 200, second.text

    invites = (await db_session.scalars(select(Invite).where(Invite.created_by == admin.id))).all()
    assert len(invites) == 2  # a fresh invite each time, not reused
    assert invites[0].token != invites[1].token
    assert len(email_spy.sends) == 2
    # Re-stamped, not just left at the first send's timestamp.
    assert second.json()["invited_at"] is not None
    assert first_invited_at is not None
