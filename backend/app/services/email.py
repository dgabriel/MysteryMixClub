import logging
from typing import Protocol

from app.config import Settings, get_settings

logger = logging.getLogger("app.services.email")

_MAGIC_LINK_SUBJECT = "Your MysteryMixClub sign-in link"
_FROM_ADDRESS = "MysteryMixClub <login@mysterymixclub.com>"


def _magic_link_html(link: str) -> str:
    return (
        "<p>Click the link below to sign in to MysteryMixClub. "
        "It expires in 15 minutes and can only be used once.</p>"
        f'<p><a href="{link}">Sign in to MysteryMixClub</a></p>'
    )


class EmailSender(Protocol):
    """Anything that can deliver a magic link to an email address."""

    def send_magic_link(self, email: str, link: str) -> None: ...


class ConsoleEmailSender:
    """Development fallback: logs the magic link instead of sending email."""

    def send_magic_link(self, email: str, link: str) -> None:
        logger.info("Magic link for %s: %s", email, link)


class ResendEmailSender:
    """Sends magic links via the Resend API."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def send_magic_link(self, email: str, link: str) -> None:
        import resend

        resend.api_key = self._api_key
        resend.Emails.send(
            {
                "from": _FROM_ADDRESS,
                "to": [email],
                "subject": _MAGIC_LINK_SUBJECT,
                "html": _magic_link_html(link),
            }
        )


def build_email_sender(settings: Settings) -> EmailSender:
    """Return a Resend sender when an API key is configured, else the console sender."""
    if settings.resend_api_key:
        return ResendEmailSender(settings.resend_api_key)
    return ConsoleEmailSender()


def get_email_sender() -> EmailSender:
    """FastAPI dependency providing the configured email sender."""
    return build_email_sender(get_settings())
