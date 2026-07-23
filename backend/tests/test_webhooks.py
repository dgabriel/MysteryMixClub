"""Tests for MYS-242's Resend Inbound webhook: POST /api/v1/webhooks/resend/inbound.

Signature verification is exercised for real (an independently computed
Svix-style HMAC, not a call into the production verify() path) so a broken
signature check would actually fail these tests. The relay itself is stubbed
via app.services.inbound_email — covered on its own in test_inbound_email.py.
"""

import base64
import hashlib
import hmac
import json
import time

import pytest

WEBHOOK_URL = "/api/v1/webhooks/resend/inbound"
_SECRET = "whsec_c29tZS10ZXN0LXNlY3JldC1ieXRlcw=="  # base64 of an arbitrary test secret


def _sign(payload: str, msg_id: str = "msg_1", timestamp: str | None = None) -> dict[str, str]:
    timestamp = timestamp or str(int(time.time()))
    secret_bytes = base64.b64decode(_SECRET[len("whsec_") :])
    signed_content = f"{msg_id}.{timestamp}.{payload}"
    sig = base64.b64encode(
        hmac.new(secret_bytes, signed_content.encode(), hashlib.sha256).digest()
    ).decode()
    return {
        "svix-id": msg_id,
        "svix-timestamp": timestamp,
        "svix-signature": f"v1,{sig}",
    }


def _event(event_type: str = "email.received", email_id: str = "email-1") -> str:
    return json.dumps(
        {
            "type": event_type,
            "data": {"email_id": email_id, "to": ["x@mysterymixclub.com"], "subject": "hi"},
        }
    )


async def test_503_when_secret_not_configured(client):
    resp = await client.post(WEBHOOK_URL, content=_event(), headers=_sign(_event()))
    assert resp.status_code == 503


class TestWebhookConfigured:
    @pytest.fixture
    def resend_webhook_secret(self) -> str:
        return _SECRET

    async def test_rejects_invalid_signature(self, client):
        payload = _event()
        headers = _sign(payload)
        headers["svix-signature"] = "v1,not-the-right-signature"
        resp = await client.post(WEBHOOK_URL, content=payload, headers=headers)
        assert resp.status_code == 401

    async def test_rejects_stale_timestamp(self, client):
        payload = _event()
        headers = _sign(payload, timestamp=str(int(time.time()) - 10_000))
        resp = await client.post(WEBHOOK_URL, content=payload, headers=headers)
        assert resp.status_code == 401

    async def test_ignores_non_receiving_events(self, client, monkeypatch):
        called = []
        monkeypatch.setattr(
            "app.api.routes.webhooks.relay_received_email",
            lambda settings, email_id: called.append(email_id),
        )
        payload = _event(event_type="email.sent")
        resp = await client.post(WEBHOOK_URL, content=payload, headers=_sign(payload))
        assert resp.status_code == 200
        assert resp.json() == {"status": "ignored"}
        assert called == []

    async def test_relays_on_valid_received_event(self, client, monkeypatch):
        called = []
        monkeypatch.setattr(
            "app.api.routes.webhooks.relay_received_email",
            lambda settings, email_id: called.append(email_id),
        )
        payload = _event(email_id="email-42")
        resp = await client.post(WEBHOOK_URL, content=payload, headers=_sign(payload))
        assert resp.status_code == 200
        assert resp.json() == {"status": "relayed"}
        assert called == ["email-42"]
