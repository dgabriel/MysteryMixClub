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
  mail-provider hiccup -- APNs' `Unregistered` (410) response, and
  `BadDeviceToken` (400) once this process has seen APNs accept the topic,
  retire the `DevicePushToken` row rather than just being logged and dropped.
  Every other rejection (bad topic, auth, throttling, 5xx, an unreadable
  body) is a provider/request problem, never evidence about the token, and
  leaves the registration alone (MysteryMixClub-4vii.33).

Two recipient queries, not one, because unlike email's single
`email_notifications` flag the PRD calls for lifecycle updates and deadline
reminders to be independently toggleable: `gather_push_recipients` (this
module) covers the six `MixEvent`s; the 24h/1-12h deadline-reminder path
(MysteryMixClub-4vii.26) filters on `push_deadline_reminders_enabled`
instead, mirroring how `advance_mixes.py`'s own `_warning_recipients` already
layers "who hasn't acted yet" on top of the base membership query.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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
from app.services.notifications import DeadlinePhase, MixEvent

logger = logging.getLogger("app.services.push_notifications")

_APNS_URL_TEMPLATE = "https://api.push.apple.com/3/device/{token}"
_REQUEST_TIMEOUT = 10.0
# https://developer.apple.com/documentation/usernotifications/handling-notification-responses-from-apns
# Only two APNs answers say a device token itself is dead: 410 `Unregistered`
# ("no longer active for the topic") and 400 `BadDeviceToken`. Every other
# status/reason describes the request, the provider credentials, throttling
# or an APNs outage -- none of which say anything about the token.
_UNREGISTERED = "Unregistered"
_BAD_DEVICE_TOKEN = "BadDeviceToken"
# An APNs error body is a tiny JSON object; anything bigger is not one.
_MAX_ERROR_BODY_BYTES = 1024
# Reasons are CamelCase words. Requiring that before a value is logged keeps
# an unexpected response body from writing arbitrary text into the journal.
_REASON_PATTERN = re.compile(r"[A-Za-z]{1,64}")
# `BadDeviceToken` is what APNs also answers for a token minted for the other
# environment, and APNs checks the device token *before* the topic (a fake
# token with a bogus topic still gets `BadDeviceToken`), so on its own it
# proves nothing about our topic. Topics for which this process has seen APNs
# answer 200 -- the only proof that the gateway + topic + credentials line
# up -- are tracked here; `BadDeviceToken` retires a token only for those.
_accepted_topics: set[str] = set()

PushOutcome = Literal["ok", "retire", "failed"]


@dataclass(frozen=True)
class PushRecipient:
    user_id: uuid.UUID
    device_token: str
    display_name: str


@dataclass(frozen=True)
class PushResult:
    """What one APNs send established. ``outcome`` is ``"retire"`` only when
    APNs said the token itself is dead (see ``_UNREGISTERED`` /
    ``_BAD_DEVICE_TOKEN``); ``reason`` is APNs' own machine-readable reason,
    already restricted to letters, so it is safe to log. ``unregistered_at``
    is APNs' ``timestamp`` on a 410 -- the last moment it confirmed the token
    was dead -- so a registration made after it is never retired."""

    outcome: PushOutcome
    status_code: int | None = None
    reason: str | None = None
    unregistered_at: datetime | None = None


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


def _reminder_title_and_body(
    phase: DeadlinePhase, club: Club, mix_: Mix, *, far: bool
) -> tuple[str, str]:
    """Restrained lock-screen copy for a deadline reminder -- same rules as
    `_title_and_body`. `far` distinguishes the ~24h-out push-only reminder
    (MysteryMixClub-4vii.26) from the closer-in 1-12h one email also sends;
    same wording shape as `notifications.send_deadline_warning`'s own
    subject line, just without the HTML body."""
    label = _mix_label(mix_)
    action = "submit to" if phase == "submission" else "vote in"
    when = "About a day left" if far else "About 12 hours left"
    return (club.name, f"{when} to {action} {label}.")


def _parse_apns_error(response: httpx.Response) -> tuple[str | None, datetime | None]:
    """Pull APNs' machine-readable ``reason`` (and, on a 410, its ``timestamp``)
    out of an error body. Bounded and defensive: an oversized, non-JSON or
    oddly-shaped body yields ``(None, None)`` rather than an exception, and a
    ``reason`` that is not a plain word is dropped so nothing but a known
    shape ever reaches a log line."""
    content = response.content
    if not content or len(content) > _MAX_ERROR_BODY_BYTES:
        return None, None
    try:
        body = json.loads(content)
    except ValueError:
        return None, None
    if not isinstance(body, dict):
        return None, None
    raw_reason = body.get("reason")
    reason = (
        raw_reason
        if isinstance(raw_reason, str) and _REASON_PATTERN.fullmatch(raw_reason)
        else None
    )
    raw_ts = body.get("timestamp")
    unregistered_at: datetime | None = None
    if isinstance(raw_ts, int) and not isinstance(raw_ts, bool):
        try:
            # APNs reports the timestamp in milliseconds since the epoch.
            unregistered_at = datetime.fromtimestamp(raw_ts / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            unregistered_at = None
    return reason, unregistered_at


async def send_push(
    client: httpx.AsyncClient,
    token_service: ApplePushTokenService,
    bundle_id: str,
    device_token: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> PushResult:
    """Send one push. Pure function, no DB access -- the caller decides what
    to do with a "retire" outcome (delete the `DevicePushToken` row), since
    the background-task dispatch path (MysteryMixClub-4vii.25) needs its own
    fresh session to do that rather than reusing a request-scoped one that
    may already be closed by the time this runs.

    The result's ``outcome`` is ``"ok"`` on a 200, ``"retire"`` only when APNs
    says the token itself is dead (410 ``Unregistered``; 400 ``BadDeviceToken``
    once this process has seen APNs accept ``bundle_id``), and ``"failed"``
    for everything else -- best-effort, mirrors `notifications._safe_send`'s
    "one bad recipient can't block the rest". Nothing that identifies a
    device, a credential or a payload is ever logged; only the HTTP status and
    APNs' own reason word.
    """
    if not token_service.is_configured:
        return PushResult("failed")
    if not bundle_id.strip():
        # APNs would answer MissingTopic; never send a request that cannot work.
        logger.warning("push send: no apns topic (bundle id) is configured")
        return PushResult("failed")
    try:
        provider_token = await token_service.get_provider_token()
    except ApplePushTokenError:
        logger.warning("push send: could not obtain an apns provider token")
        return PushResult("failed")

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
        return PushResult("failed")

    status_code = response.status_code
    if status_code == 200:
        _accepted_topics.add(bundle_id)
        logger.info("push send: accepted by apns")
        return PushResult("ok", status_code)

    reason, unregistered_at = _parse_apns_error(response)
    if status_code == 410 and reason == _UNREGISTERED:
        return PushResult("retire", status_code, reason, unregistered_at)
    if status_code == 400 and reason == _BAD_DEVICE_TOKEN:
        if bundle_id in _accepted_topics:
            return PushResult("retire", status_code, reason)
        logger.warning(
            "push send: apns answered BadDeviceToken but has not yet accepted this topic in "
            "this process, so the token is kept (a wrong environment or topic looks the same)"
        )
        return PushResult("failed", status_code, reason)
    logger.warning(
        "push send: apns rejected the request (status=%s reason=%s)",
        status_code,
        reason or "unreadable",
    )
    return PushResult("failed", status_code, reason)


async def _retire_device_token(
    device_token: str, user_id: uuid.UUID, *, not_updated_after: datetime
) -> bool:
    """Delete the registration APNs just judged dead, in its own fresh session
    -- safe to call from a background task after the request's own session
    has already closed. Returns whether a row was deleted.

    Scoped to the exact ``(token, user)`` association the send used and to
    rows not registered after ``not_updated_after`` (APNs' own ``timestamp``
    on a 410, otherwise the moment the send began): a device that re-registers
    -- same token or handed to another account -- while the send was in
    flight has a *newer* association that this verdict says nothing about."""
    async with async_session_factory() as db:
        deleted = await db.scalar(
            delete(DevicePushToken)
            .where(
                DevicePushToken.device_token == device_token,
                DevicePushToken.user_id == user_id,
                DevicePushToken.updated_at <= not_updated_after,
            )
            .returning(DevicePushToken.id)
        )
        await db.commit()
    return deleted is not None


async def _dispatch_one(
    client: httpx.AsyncClient,
    token_service: ApplePushTokenService,
    bundle_id: str,
    recipient: PushRecipient,
    title: str,
    body: str,
    data: dict[str, str] | None,
) -> None:
    sent_at = datetime.now(timezone.utc)
    result = await send_push(
        client, token_service, bundle_id, recipient.device_token, title, body, data
    )
    if result.outcome != "retire":
        return
    # A 410's timestamp only ever narrows the guard: never retire a registration
    # made after this send began, whatever the timestamp says.
    cutoff = min(result.unregistered_at, sent_at) if result.unregistered_at else sent_at
    retired = await _retire_device_token(
        recipient.device_token, recipient.user_id, not_updated_after=cutoff
    )
    logger.warning(
        "push send: %s (status=%s reason=%s)",
        (
            "retired a registration apns reports as dead"
            if retired
            else "did not retire: the registration was newer than the verdict, "
            "reassigned to another account, or already removed"
        ),
        result.status_code,
        result.reason,
    )


def _worth_sending(token_service: ApplePushTokenService, recipients: list[PushRecipient]) -> bool:
    """False when there is nothing to send or APNs is not configured. The
    second case is logged: silently dropping a real recipient's push is
    indistinguishable from "APNs accepted it" in the journal otherwise."""
    if not recipients:
        return False
    if not token_service.is_configured:
        logger.warning(
            "push send: skipped %d recipient(s), apns credentials are not configured",
            len(recipients),
        )
        return False
    return True


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
    if not _worth_sending(token_service, recipients):
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


async def _send_to_all(
    token_service: ApplePushTokenService,
    settings: Settings,
    recipients: list[PushRecipient],
    title: str,
    body: str,
    data: dict[str, str],
) -> None:
    """Shared synchronous-path dispatch loop: one short-lived HTTP client,
    one send per recipient. No-ops when unconfigured or empty -- the actual
    graceful-degradation check callers rely on."""
    if not _worth_sending(token_service, recipients):
        return
    async with httpx.AsyncClient(http2=True, timeout=_REQUEST_TIMEOUT) as client:
        for r in recipients:
            await _dispatch_one(
                client, token_service, settings.apple_sign_in_bundle_id, r, title, body, data
            )


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
    title, body = _title_and_body(event, club, mix_)
    data = {"club_id": str(club.id), "mix_id": str(mix_.id), "event": event}
    await _send_to_all(token_service, settings, recipients, title, body, data)


async def send_push_reminder(
    token_service: ApplePushTokenService,
    settings: Settings,
    recipients: list[PushRecipient],
    club: Club,
    mix_: Mix,
    phase: DeadlinePhase,
    *,
    far: bool,
) -> None:
    """Deadline-reminder push (MysteryMixClub-4vii.26) -- the push
    counterpart of `notifications.send_deadline_warning`, but keyed on
    `DeadlinePhase` rather than `MixEvent` since a reminder isn't one of the
    six lifecycle events. `far` selects the ~24h-out copy vs. the 1-12h-out
    one; the deadline job calls this twice, independently, for the two
    cadences (MysteryMixClub-4vii.26's own "both" cadence decision)."""
    title, body = _reminder_title_and_body(phase, club, mix_, far=far)
    data = {"club_id": str(club.id), "mix_id": str(mix_.id), "event": f"{phase}_deadline"}
    await _send_to_all(token_service, settings, recipients, title, body, data)
