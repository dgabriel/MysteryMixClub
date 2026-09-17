"""Push notifications via APNs (MysteryMixClub-4vii.25, IOS-04).

The push twin of `notifications.py`: same `MixEvent`-driven dispatch (reused
from there directly, not redefined), same two-path split (BackgroundTasks for
the API routes, synchronous for the deadline job), same best-effort "one bad
recipient can't block the rest" philosophy. Three things are genuinely
different from email, not just renamed:

- **Recipients are per device, not per user.** `PushRecipient` carries a
  `device_token`; a member signed in on two phones gets two sends. Gating is
  on `User.push_lifecycle_enabled` (this module) rather than
  `User.email_notifications` -- the PRD calls for push to have its own
  preference, independent of email and of the deadline-reminder preference
  below it.
- **Copy is short and restrained, not HTML.** Lock-screen text never names a
  submitter, reveals participation mode, or previews hidden results (PRD,
  IOS-04) -- "Voting is open for Mystery Mix 4 in The Mystery Mix Club", never
  who submitted what.
- **A failed send can mean the token itself is dead**, not just a transient
  mail-provider hiccup -- APNs' own `BadDeviceToken`/`Unregistered` responses
  retire the `DevicePushToken` row rather than just being logged and dropped.

Two recipient queries, not one, because unlike email's single
`email_notifications` flag the PRD calls for lifecycle updates and deadline
reminders to be independently toggleable: `gather_push_recipients` (this
module) covers the six `MixEvent`s; the 24h/1-12h deadline-reminder path
(MysteryMixClub-4vii.26) filters on `push_deadline_reminders_enabled`
instead, mirroring how `advance_mixes.py`'s own `_warning_recipients` already
layers "who hasn't acted yet" on top of the base membership query.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Literal

import httpx
from fastapi import BackgroundTasks
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.session import async_session_factory
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.device_push_token import DevicePushToken
from app.models.mix import Mix
from app.models.user import User
from app.services.apple_push_token import ApplePushTokenError, ApplePushTokenService
from app.services.notifications import MixEvent

logger = logging.getLogger("app.services.push_notifications")

_APNS_URL_TEMPLATE = "https://api.push.apple.com/3/device/{token}"
_REQUEST_TIMEOUT = 10.0
# APNs' own signal that a token is permanently dead, not a transient failure —
# https://developer.apple.com/documentation/usernotifications/handling-notification-responses-from-apns
_RETIRE_STATUS_CODES = (400, 410)


@dataclass(frozen=True)
class PushRecipient:
    user_id: uuid.UUID
    device_token: str
    display_name: str


async def gather_push_recipients(db: AsyncSession, league_id: uuid.UUID) -> list[PushRecipient]:
    """One row per live device of a current, live-account, lifecycle-push-
    enabled club member. A member with N registered devices appears N times
    (email's `gather_recipients` returns one row per user; this can't, since
    every device needs its own send). Mirrors that function's membership/
    account-liveness filters exactly, swapping `email_notifications` for
    `push_lifecycle_enabled`."""
    rows = await db.execute(
        select(User.id, DevicePushToken.device_token, User.display_name)
        .join(ClubMember, ClubMember.user_id == User.id)
        .join(DevicePushToken, DevicePushToken.user_id == User.id)
        .where(
            ClubMember.club_id == league_id,
            ClubMember.removed_at.is_(None),
            User.deleted_at.is_(None),
            User.push_lifecycle_enabled.is_(True),
        )
    )
    return [PushRecipient(user_id=r[0], device_token=r[1], display_name=r[2]) for r in rows.all()]


async def organizer_push_recipients(db: AsyncSession, club: Club) -> list[PushRecipient]:
    """The organizer's own device(s), or empty if the club has no organizer
    (hard-purged) or the organizer has lifecycle push off. Push counterpart
    of `organizer_recipient` -- used for `needs_theme`, which must never
    reach the whole club."""
    if club.organizer_id is None:
        return []
    recipients = await gather_push_recipients(db, club.id)
    return [r for r in recipients if r.user_id == club.organizer_id]


async def gather_push_deadline_recipients(
    db: AsyncSession, league_id: uuid.UUID
) -> list[PushRecipient]:
    """Same shape as `gather_push_recipients`, gated on
    `push_deadline_reminders_enabled` instead of `push_lifecycle_enabled` --
    the PRD's two preferences are independent, so a member can want one
    channel without the other. Callers still need to further filter to who
    actually has an outstanding action (mirrors `_warning_recipients` in
    `advance_mixes.py`, MysteryMixClub-4vii.26)."""
    rows = await db.execute(
        select(User.id, DevicePushToken.device_token, User.display_name)
        .join(ClubMember, ClubMember.user_id == User.id)
        .join(DevicePushToken, DevicePushToken.user_id == User.id)
        .where(
            ClubMember.club_id == league_id,
            ClubMember.removed_at.is_(None),
            User.deleted_at.is_(None),
            User.push_deadline_reminders_enabled.is_(True),
        )
    )
    return [PushRecipient(user_id=r[0], device_token=r[1], display_name=r[2]) for r in rows.all()]


def _mix_label(mix_: Mix) -> str:
    """Same label email uses (`notifications._mix_label`, duplicated rather
    than imported since a theme is the organizer's own public content, not
    hidden data -- safe on a lock screen)."""
    if mix_.theme:
        return f"Mystery Mix {mix_.mix_number}: {mix_.theme}"
    return f"Mystery Mix {mix_.mix_number}"


def _title_and_body(event: MixEvent, club: Club, mix_: Mix) -> tuple[str, str]:
    """Restrained lock-screen copy for `event` -- never a submitter's name,
    participation mode, or a hidden result (PRD, IOS-04). Club name and mix
    theme are the organizer's own public content, not hidden data."""
    label = _mix_label(mix_)
    if event == "submission_open":
        return (club.name, f"{label} is open for submissions.")
    if event == "voting_open":
        return (club.name, f"Voting is open for {label}.")
    if event == "mix_closed":
        return (club.name, f"{label} results are in.")
    if event == "voting_extended":
        return (club.name, f"Voting for {label} has been extended.")
    if event == "needs_theme":
        return (club.name, f"{label} needs a theme before it can open.")
    # club_complete
    return (club.name, f"{club.name} has wrapped after its final mystery mix.")


async def send_push(
    client: httpx.AsyncClient,
    token_service: ApplePushTokenService,
    bundle_id: str,
    device_token: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> Literal["ok", "retire", "failed"]:
    """Send one push. Pure function, no DB access -- the caller decides what
    to do with a "retire" outcome (delete the `DevicePushToken` row), since
    the background-task dispatch path (MysteryMixClub-4vii.25) needs its own
    fresh session to do that rather than reusing a request-scoped one that
    may already be closed by the time this runs.

    Returns ``"ok"`` on success, ``"retire"`` when APNs says the token is
    permanently dead (400 BadDeviceToken / 410 Unregistered), ``"failed"``
    for anything else (network error, other non-2xx) -- best-effort, mirrors
    `notifications._safe_send`'s "one bad recipient can't block the rest".
    """
    if not token_service.is_configured:
        return "failed"
    try:
        provider_token = await token_service.get_provider_token()
    except ApplePushTokenError:
        logger.warning("push send: could not obtain an apns provider token")
        return "failed"

    payload: dict[str, object] = {
        "aps": {"alert": {"title": title, "body": body}, "sound": "default"}
    }
    if data:
        payload.update(data)

    try:
        response = await client.post(
            _APNS_URL_TEMPLATE.format(token=device_token),
            json=payload,
            headers={
                "authorization": f"bearer {provider_token}",
                "apns-topic": bundle_id,
                "apns-push-type": "alert",
                "apns-priority": "10",
            },
        )
    except httpx.HTTPError:
        logger.warning("push send: request to apns failed")
        return "failed"

    if response.status_code == 200:
        return "ok"
    if response.status_code in _RETIRE_STATUS_CODES:
        return "retire"
    logger.warning("push send: apns returned %s", response.status_code)
    return "failed"


async def _retire_device_token(device_token: str) -> None:
    """Delete a dead token in its own fresh session -- safe to call from a
    background task after the request's own session has already closed."""
    async with async_session_factory() as db:
        await db.execute(
            delete(DevicePushToken).where(DevicePushToken.device_token == device_token)
        )
        await db.commit()


async def _dispatch_one(
    client: httpx.AsyncClient,
    token_service: ApplePushTokenService,
    bundle_id: str,
    recipient: PushRecipient,
    title: str,
    body: str,
    data: dict[str, str] | None,
) -> None:
    outcome = await send_push(
        client, token_service, bundle_id, recipient.device_token, title, body, data
    )
    if outcome == "retire":
        await _retire_device_token(recipient.device_token)


def queue_push_event(
    background_tasks: BackgroundTasks,
    token_service: ApplePushTokenService,
    settings: Settings,
    recipients: list[PushRecipient],
    club: Club,
    mix_: Mix,
    event: MixEvent,
) -> None:
    """Schedule one push per recipient for `event`, off the request.

    No-ops when unconfigured or there are no recipients -- same graceful-
    degradation shape as `queue_mix_event`."""
    if not recipients or not token_service.is_configured:
        return
    title, body = _title_and_body(event, club, mix_)
    data = {"club_id": str(club.id), "mix_id": str(mix_.id), "event": event}
    for r in recipients:
        background_tasks.add_task(
            _queue_one_push, token_service, settings.apple_sign_in_bundle_id, r, title, body, data
        )


async def _queue_one_push(
    token_service: ApplePushTokenService,
    bundle_id: str,
    recipient: PushRecipient,
    title: str,
    body: str,
    data: dict[str, str],
) -> None:
    """The actual background-task body: opens its own short-lived HTTP
    client (a BackgroundTasks callback has no client to reuse) and dispatches
    one push, retiring the token on a dead-token response."""
    async with httpx.AsyncClient(http2=True, timeout=_REQUEST_TIMEOUT) as client:
        await _dispatch_one(client, token_service, bundle_id, recipient, title, body, data)


async def send_push_event(
    token_service: ApplePushTokenService,
    settings: Settings,
    recipients: list[PushRecipient],
    club: Club,
    mix_: Mix,
    event: MixEvent,
) -> None:
    """Synchronous twin of `queue_push_event`, for the deadline job (no
    BackgroundTasks available there). No-ops when unconfigured or empty."""
    if not recipients or not token_service.is_configured:
        return
    title, body = _title_and_body(event, club, mix_)
    data = {"club_id": str(club.id), "mix_id": str(mix_.id), "event": event}
    async with httpx.AsyncClient(http2=True, timeout=_REQUEST_TIMEOUT) as client:
        for r in recipients:
            await _dispatch_one(
                client, token_service, settings.apple_sign_in_bundle_id, r, title, body, data
            )
