"""Tests for MYS-242's relay service: fetch a Resend Inbound message and
forward it to the ops inbox. Isolated from the webhook route/signature
verification, covered separately in test_webhooks.py."""

from app.config import Settings
from app.services.inbound_email import relay_received_email


def _received(**overrides) -> dict:
    base = {
        "id": "email-1",
        "to": ["random@mysterymixclub.com"],
        "from": "someone@example.com",
        "subject": "hello",
        "html": "<p>hi</p>",
        "text": "hi",
    }
    base.update(overrides)
    return base


def test_relay_fetches_and_forwards(monkeypatch):
    import resend

    fetched_ids = []
    monkeypatch.setattr(
        resend.EmailsReceiving,
        "get",
        lambda email_id: fetched_ids.append(email_id) or _received(),
    )
    sent = []
    monkeypatch.setattr(resend.Emails, "send", lambda params: sent.append(params) or {})

    settings = Settings(resend_api_key="key", inbound_email_forward_to="ops@example.com")
    relay_received_email(settings, "email-1")

    assert fetched_ids == ["email-1"]
    assert len(sent) == 1
    params = sent[0]
    assert params["to"] == ["ops@example.com"]
    assert params["reply_to"] == ["someone@example.com"]
    assert "random@mysterymixclub.com" in params["subject"]
    assert "hello" in params["subject"]
    assert params["html"] == "<p>hi</p>"


def test_relay_falls_back_to_escaped_text_when_no_html(monkeypatch):
    import resend

    monkeypatch.setattr(
        resend.EmailsReceiving,
        "get",
        lambda email_id: _received(html=None, text="<script>alert(1)</script>"),
    )
    sent = []
    monkeypatch.setattr(resend.Emails, "send", lambda params: sent.append(params) or {})

    settings = Settings(resend_api_key="key")
    relay_received_email(settings, "email-1")

    assert "<script>" not in sent[0]["html"]
    assert "&lt;script&gt;" in sent[0]["html"]
