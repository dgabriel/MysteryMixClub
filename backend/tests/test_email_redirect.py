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

    sender.send("real@user.com", "Round open", "<p>hi</p>", {"List-Unsubscribe": "<u>"})

    assert len(spy.sends) == 1
    to, subject, html, headers = spy.sends[0]
    assert to == "sink@test.dev"
    assert "real@user.com" in subject  # who it was meant for
    assert subject.endswith("Round open")
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
