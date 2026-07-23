"""Inbound webhooks from third-party services (MYS-242: Resend Inbound).

Unauthenticated by nature (the caller is Resend, not a logged-in user) —
trust comes from the Svix signature instead of a JWT. Kept deliberately thin:
verify, fetch, relay. No retry/dedupe/queue — Resend's own delivery to this
endpoint already retries on failure, so a duplicate relay on a retried
webhook is an acceptable, harmless edge rather than something to engineer
around (see MYS-242).
"""

import logging

import resend
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.services.inbound_email import relay_received_email

logger = logging.getLogger("app.api.routes.webhooks")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/resend/inbound", status_code=status.HTTP_200_OK)
async def resend_inbound_webhook(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if not settings.resend_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="inbound webhook not configured",
        )

    raw_body = await request.body()
    try:
        resend.Webhooks.verify(
            {
                "payload": raw_body.decode("utf-8"),
                "headers": {
                    "id": request.headers.get("svix-id", ""),
                    "timestamp": request.headers.get("svix-timestamp", ""),
                    "signature": request.headers.get("svix-signature", ""),
                },
                "webhook_secret": settings.resend_webhook_secret,
            }
        )
    except ValueError:
        logger.warning("rejected resend webhook with invalid signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature"
        ) from None

    event = await request.json()
    if event.get("type") != "email.received":
        return {"status": "ignored"}

    relay_received_email(settings, event["data"]["email_id"])
    return {"status": "relayed"}
