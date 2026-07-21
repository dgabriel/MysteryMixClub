"""Tests for MYS-215: the public waitlist (temporary pre-launch flow).

Covers:
  GET  /api/v1/waitlist/enabled — flag-state check the frontend uses to
                                   decide whether to render the form
  POST /api/v1/waitlist         — join: flag-gated, format-validated,
                                   duplicate-rejected, email-normalized

Admin-side (list + invite-from-waitlist) is covered in
test_admin_waitlist.py.
"""

import pytest
from sqlalchemy import select

from app.api.routes import waitlist as waitlist_routes
from app.models.waitlist_entry import WaitlistEntry

ENABLED_URL = "/api/v1/waitlist/enabled"
JOIN_URL = "/api/v1/waitlist"


@pytest.fixture(autouse=True)
def _reset_join_rate_limit():
    """The per-IP rate limiter (MYS-215) is a module-level dict so it works
    across requests within one process — which also means it persists across
    tests unless reset. All requests from this suite's ASGI test client share
    one synthetic IP, so without this every test would draw from the same
    budget."""
    waitlist_routes._join_attempts.clear()
    yield
    waitlist_routes._join_attempts.clear()


async def test_enabled_reflects_flag_off_by_default(client):
    # The shared client fixture's waitlist_enabled default (conftest.py)
    # matches the flag's own production-safe default.
    resp = await client.get(ENABLED_URL)
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False}


async def test_join_404_when_disabled(client):
    resp = await client.post(JOIN_URL, json={"email": "late@example.com"})
    assert resp.status_code == 404


class TestWaitlistWhenEnabled:
    @pytest.fixture
    def waitlist_enabled(self) -> bool:
        return True

    async def test_enabled_reflects_flag_on(self, client):
        resp = await client.get(ENABLED_URL)
        assert resp.status_code == 200
        assert resp.json() == {"enabled": True}

    async def test_join_succeeds(self, client, db_session):
        resp = await client.post(JOIN_URL, json={"email": "Fan@Example.com"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # Normalized to lowercase (matches the auth.py convention).
        assert body["email"] == "fan@example.com"
        assert body["id"]
        assert body["created_at"]

        entry = await db_session.scalar(
            select(WaitlistEntry).where(WaitlistEntry.email == "fan@example.com")
        )
        assert entry is not None

    async def test_join_rejects_duplicate_case_insensitive(self, client):
        first = await client.post(JOIN_URL, json={"email": "dup@example.com"})
        assert first.status_code == 201, first.text

        second = await client.post(JOIN_URL, json={"email": "DUP@example.com"})
        assert second.status_code == 409, second.text
        assert "already" in second.json()["detail"]

    async def test_join_rejects_malformed_email(self, client):
        resp = await client.post(JOIN_URL, json={"email": "not-an-email"})
        assert resp.status_code == 422

    async def test_join_requires_email_field(self, client):
        resp = await client.post(JOIN_URL, json={})
        assert resp.status_code == 422

    async def test_join_rate_limited_after_five_per_ip(self, client):
        for i in range(5):
            resp = await client.post(JOIN_URL, json={"email": f"person{i}@example.com"})
            assert resp.status_code == 201, f"attempt {i + 1} -> {resp.status_code}: {resp.text}"

        sixth = await client.post(JOIN_URL, json={"email": "person5@example.com"})
        assert sixth.status_code == 429, sixth.text
