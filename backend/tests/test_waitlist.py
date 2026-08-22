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
from sqlalchemy import func, select

from app.models.waitlist_entry import WaitlistEntry
from app.models.waitlist_join_attempt import WaitlistJoinAttempt

ENABLED_URL = "/api/v1/waitlist/enabled"
JOIN_URL = "/api/v1/waitlist"


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

    async def test_join_rate_limit_is_db_backed_not_process_local(self, client, db_session):
        # The regression this guards against (MysteryMixClub-dicr): the
        # original in-memory dict was only correct under a single worker
        # process, and silently became N x too permissive under multi-worker
        # gunicorn (MYS-259) since each worker had its own copy. A row landing
        # in the database (not just an in-process counter) is what makes the
        # limit shared across workers.
        resp = await client.post(JOIN_URL, json={"email": "counted@example.com"})
        assert resp.status_code == 201, resp.text

        count = await db_session.scalar(select(func.count()).select_from(WaitlistJoinAttempt))
        assert count == 1

    async def test_join_rate_limit_rejection_is_not_itself_recorded(self, client, db_session):
        # Mirrors OAuthCallbackAttempt's behavior: the request that trips the
        # limit doesn't add a 6th row, so a sustained attacker's row count
        # stays bounded at the limit rather than growing unboundedly.
        for i in range(5):
            resp = await client.post(JOIN_URL, json={"email": f"person{i}@example.com"})
            assert resp.status_code == 201, resp.text

        rejected = await client.post(JOIN_URL, json={"email": "person5@example.com"})
        assert rejected.status_code == 429, rejected.text

        count = await db_session.scalar(select(func.count()).select_from(WaitlistJoinAttempt))
        assert count == 5
