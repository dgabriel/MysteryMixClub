"""Tests for the staging email sink (EMAIL_REDIRECT_TO_TEST).

Verifies build_email_sender wires the redirect wrapper from settings, that the
wrapper rewrites the recipient (preserving subject/html/headers and the intended
address in the subject), and the fail-safe when the flag is on with no recipient.
"""

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.config import Settings
from app.services.email import (
    ConsoleEmailSender,
    RedirectingEmailSender,
    ResendEmailSender,
    build_email_sender,
)


@contextmanager
def _capture_email_log():
    """Collect log messages from the email logger.

    Not ``caplog``: ``app/main.py`` sets ``propagate = False`` on the ``app``
    logger in development, so records never reach the root logger caplog
    listens on (see test_auth_google.py's ``_capture_auth_warnings`` for the
    same trap). Attaching to the logger itself is what actually observes them.
    """
    messages: list[str] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    logger = logging.getLogger("app.services.email")
    handler = _Collector(level=logging.INFO)
    logger.addHandler(handler)
    try:
        yield messages
    finally:
        logger.removeHandler(handler)


@dataclass
class _Spy:
    sends: list[tuple[str, str, str, dict | None]] = field(default_factory=list)
    magic: list[tuple[str, str]] = field(default_factory=list)
    resets: list[tuple[str, str]] = field(default_factory=list)

    def send_magic_link(self, email: str, link: str) -> None:
        self.magic.append((email, link))

    def send_password_reset(self, email: str, link: str) -> None:
        self.resets.append((email, link))

    def send(self, email, subject, html, headers=None) -> None:
        self.sends.append((email, subject, html, headers))


def test_redirect_rewrites_recipient_and_tags_subject():
    spy = _Spy()
    sender = RedirectingEmailSender(spy, "sink@test.dev")

    sender.send("real@user.com", "Mix open", "<p>hi</p>", {"List-Unsubscribe": "<u>"})

    assert len(spy.sends) == 1
    to, subject, html, headers = spy.sends[0]
    assert to == "sink@test.dev"
    assert "real@user.com" in subject  # who it was meant for
    assert subject.endswith("Mix open")
    assert html == "<p>hi</p>"
    assert headers == {"List-Unsubscribe": "<u>"}


def test_redirect_covers_magic_links():
    spy = _Spy()
    sender = RedirectingEmailSender(spy, "sink@test.dev")

    sender.send_magic_link("real@user.com", "https://app/verify?token=x")

    assert spy.magic == [("sink@test.dev", "https://app/verify?token=x")]


def test_build_returns_wrapper_when_flag_on_with_recipient():
    settings = Settings(
        resend_api_key="key", email_redirect_to_test=True, email_test_recipient="sink@test.dev"
    )
    sender = build_email_sender(settings)
    assert isinstance(sender, RedirectingEmailSender)


def test_build_suppresses_when_flag_on_without_recipient():
    settings = Settings(resend_api_key="key", email_redirect_to_test=True, email_test_recipient="")
    sender = build_email_sender(settings)
    # Fail-safe: console (no real send), not the Resend sender.
    assert isinstance(sender, ConsoleEmailSender)


def test_build_normal_delivery_when_flag_off():
    settings = Settings(resend_api_key="key", email_redirect_to_test=False)
    sender = build_email_sender(settings)
    assert isinstance(sender, ResendEmailSender)


def _capture_resend_params(monkeypatch) -> list[dict]:
    """Stub resend.Emails.send so tests inspect params without a network call."""
    import resend

    captured: list[dict] = []
    monkeypatch.setattr(resend.Emails, "send", lambda params: captured.append(params) or {})
    return captured


def test_resend_uses_per_purpose_from_without_override(monkeypatch):
    captured = _capture_resend_params(monkeypatch)
    sender = ResendEmailSender("key")

    sender.send_magic_link("u@x.com", "https://app/verify?token=t")
    sender.send("u@x.com", "Mix open", "<p>hi</p>")

    assert captured[0]["from"] == "MysteryMixClub <login@mysterymixclub.com>"
    assert captured[1]["from"] == "MysteryMixClub <notifications@mysterymixclub.com>"


def test_resend_from_override_applies_to_all_mail(monkeypatch):
    captured = _capture_resend_params(monkeypatch)
    sender = ResendEmailSender("key", from_override="onboarding@resend.dev")

    sender.send_magic_link("u@x.com", "https://app/verify?token=t")
    sender.send("u@x.com", "Mix open", "<p>hi</p>")

    assert [p["from"] for p in captured] == ["onboarding@resend.dev", "onboarding@resend.dev"]


def test_build_passes_email_from_to_resend(monkeypatch):
    captured = _capture_resend_params(monkeypatch)
    settings = Settings(resend_api_key="key", email_from="onboarding@resend.dev")

    sender = build_email_sender(settings)
    sender.send_magic_link("u@x.com", "https://app/verify?token=t")

    assert isinstance(sender, ResendEmailSender)
    assert captured[0]["from"] == "onboarding@resend.dev"


def test_console_sender_logs_full_link_by_default():
    sender = ConsoleEmailSender()

    with _capture_email_log() as messages:
        sender.send_magic_link("u@x.com", "https://app/verify?token=secret-token")
        sender.send_password_reset("u@x.com", "https://app/reset?token=secret-token")

    text = "\n".join(messages)
    assert "https://app/verify?token=secret-token" in text
    assert "https://app/reset?token=secret-token" in text


def test_console_sender_redacts_link_when_flagged():
    sender = ConsoleEmailSender(redact=True)

    with _capture_email_log() as messages:
        sender.send_magic_link("u@x.com", "https://app/verify?token=secret-token")
        sender.send_password_reset("u@x.com", "https://app/reset?token=secret-token")

    text = "\n".join(messages)
    assert "secret-token" not in text
    assert "u@x.com" in text


def test_build_redacts_console_fallback_outside_development():
    # No resend_api_key -> falls back to ConsoleEmailSender. Outside
    # development, that fallback must not log the raw token.
    settings = Settings(environment="staging")
    sender = build_email_sender(settings)

    assert isinstance(sender, ConsoleEmailSender)
    assert sender._redact is True


def test_build_does_not_redact_console_fallback_in_development():
    settings = Settings(environment="development")
    sender = build_email_sender(settings)

    assert isinstance(sender, ConsoleEmailSender)
    assert sender._redact is False
