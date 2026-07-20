"""Tests for the staging email sink (EMAIL_REDIRECT_TO_TEST).

Verifies build_email_sender wires the redirect wrapper from settings, that the
wrapper rewrites the recipient (preserving subject/html/headers and the intended
address in the subject), and the fail-safe when the flag is on with no recipient.
"""

from dataclasses import dataclass, field

from app.config import Settings
from app.services.email import (
    ConsoleEmailSender,
    RedirectingEmailSender,
    ResendEmailSender,
    build_email_sender,
)


@dataclass
class _Spy:
    sends: list[tuple[str, str, str, dict | None]] = field(default_factory=list)
    magic: list[tuple[str, str]] = field(default_factory=list)

    def send_magic_link(self, email: str, link: str) -> None:
        self.magic.append((email, link))

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
