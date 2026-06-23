import logging
from typing import Protocol

from app.config import Settings, get_settings

logger = logging.getLogger("app.services.email")

_MAGIC_LINK_SUBJECT = "Your MysteryMixClub sign-in link"
_FROM_ADDRESS = "MysteryMixClub <login@mysterymixclub.com>"
_NOTIFY_FROM_ADDRESS = "MysteryMixClub <notifications@mysterymixclub.com>"


def _magic_link_html(link: str) -> str:
    return (
        "<p>Click the link below to sign in to MysteryMixClub. "
        "It expires in 15 minutes and can only be used once.</p>"
        f'<p><a href="{link}">Sign in to MysteryMixClub</a></p>'
    )


class EmailSender(Protocol):
    """Anything that can deliver email — magic links and general notifications."""

    def send_magic_link(self, email: str, link: str) -> None: ...

    def send(
        self, email: str, subject: str, html: str, headers: dict[str, str] | None = None
    ) -> None:
        """Deliver a general (non-magic-link) notification email.

        ``headers`` carries extra MIME headers (e.g. ``List-Unsubscribe`` for
        one-click unsubscribe), which improve deliverability for bulk-ish mail."""
        ...


class ConsoleEmailSender:
    """Development fallback: logs emails instead of sending them."""

    def send_magic_link(self, email: str, link: str) -> None:
        logger.info("Magic link for %s: %s", email, link)

    def send(
        self, email: str, subject: str, html: str, headers: dict[str, str] | None = None
    ) -> None:
        logger.info("Email to %s — %s", email, subject)


class ResendEmailSender:
    """Sends email via the Resend API."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def _send(
        self,
        from_address: str,
        email: str,
        subject: str,
        html: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        import resend

        resend.api_key = self._api_key
        params: resend.Emails.SendParams = {
            "from": from_address,
            "to": [email],
            "subject": subject,
            "html": html,
        }
        if headers:
            params["headers"] = headers
        resend.Emails.send(params)

    def send_magic_link(self, email: str, link: str) -> None:
        self._send(_FROM_ADDRESS, email, _MAGIC_LINK_SUBJECT, _magic_link_html(link))

    def send(
        self, email: str, subject: str, html: str, headers: dict[str, str] | None = None
    ) -> None:
        self._send(_NOTIFY_FROM_ADDRESS, email, subject, html, headers)


class RedirectingEmailSender:
    """Wraps a real sender and redirects every recipient to one address — a
    staging email sink.

    Toggled by ``EMAIL_REDIRECT_TO_TEST`` so staging can be flipped between real
    delivery and a test inbox via env, no redeploy. Covers magic links and
    notifications alike. The intended recipient is preserved in the subject so
    the sink shows who each message was actually for."""

    def __init__(self, inner: EmailSender, test_recipient: str) -> None:
        self._inner = inner
        self._to = test_recipient

    def send_magic_link(self, email: str, link: str) -> None:
        self._inner.send_magic_link(self._to, link)

    def send(
        self, email: str, subject: str, html: str, headers: dict[str, str] | None = None
    ) -> None:
        self._inner.send(self._to, f"[→ {email}] {subject}", html, headers)


def build_email_sender(settings: Settings) -> EmailSender:
    """Return the configured email sender.

    Resend when an API key is set, else the console logger. When
    ``EMAIL_REDIRECT_TO_TEST`` is on, the chosen sender is wrapped so every
    message is redirected to ``EMAIL_TEST_RECIPIENT`` — and if that's unset, email
    is suppressed (console) rather than risk reaching real recipients."""
    base: EmailSender = (
        ResendEmailSender(settings.resend_api_key)
        if settings.resend_api_key
        else ConsoleEmailSender()
    )
    if settings.email_redirect_to_test:
        if not settings.email_test_recipient:
            logger.warning(
                "EMAIL_REDIRECT_TO_TEST is on but EMAIL_TEST_RECIPIENT is unset; "
                "suppressing email to avoid reaching real recipients"
            )
            return ConsoleEmailSender()
        return RedirectingEmailSender(base, settings.email_test_recipient)
    return base


def get_email_sender() -> EmailSender:
    """FastAPI dependency providing the configured email sender."""
    return build_email_sender(get_settings())
