import html
import logging

import resend

from app.config import Settings

logger = logging.getLogger("app.services.inbound_email")

_FROM_ADDRESS = "MysteryMixClub Inbound <inbound@mysterymixclub.com>"


def relay_received_email(settings: Settings, email_id: str) -> None:
    """Fetch a Resend Inbound message and relay it to the ops inbox.

    Resend's webhook payload carries only metadata; the body/attachments come
    from a separate API call (``Receiving.get``). The relay can't send *as*
    the original external sender (Resend's domain auth only covers
    mysterymixclub.com), so it goes out from a fixed local address with the
    original sender set as Reply-To and the original recipient noted in the
    subject, mirroring the existing test-inbox redirect convention in
    ``services/email.py``.
    """
    resend.api_key = settings.resend_api_key
    received = resend.EmailsReceiving.get(email_id)

    original_to = ", ".join(received["to"])
    resend.Emails.send(
        {
            "from": _FROM_ADDRESS,
            "to": [settings.inbound_email_forward_to],
            "subject": f"[{original_to}] {received['subject']}",
            "reply_to": [received["from"]],
            "html": received.get("html") or f"<pre>{html.escape(received.get('text') or '')}</pre>",
        }
    )
    logger.info(
        "relayed inbound email %s (to=%s) -> %s",
        email_id,
        original_to,
        settings.inbound_email_forward_to,
    )
