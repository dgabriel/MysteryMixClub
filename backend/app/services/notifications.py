"""Mix-lifecycle email notifications (MYS-109) and club-join welcome email (MYS-148).

Generalizes the magic-link mailer into per-event notifications fired when a
mix changes state. Recipients are the club's current members who have email
notifications enabled; sending is best-effort so a slow or failing mail provider
never blocks (or fails) the caller.

Two dispatch paths share the same body-building code:
- the API path (:func:`queue_mix_event` / :func:`queue_club_joined`) runs each
  send in a FastAPI background task, off the request; and
- the job path (:func:`send_mix_event` / :func:`send_deadline_warning` /
  :func:`send_empty_mix_notice`) sends synchronously, for the deadline
  force-advance job (MYS-145/162), which has no request or ``BackgroundTasks``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_unsubscribe_token
from app.config import Settings
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.user import User
from app.services.email import EmailSender

logger = logging.getLogger("app.services.notifications")

# The lifecycle moments worth an email. Kept distinct from the raw mix states
# so "the next mix auto-opened" and "this mix opened" can both map to a
# submission_open notification for their respective mixes.
MixEvent = Literal[
    "submission_open",
    "voting_open",
    "mix_closed",
    "club_complete",
    "voting_extended",
    # The mix that would auto-open next (on a close) has no theme (MYS-211) —
    # organizer-only, never sent to the whole club. See organizer_recipient().
    "needs_theme",
]

# The two deadline phases a mix can be warned about (MYS-162).
DeadlinePhase = Literal["submission", "voting"]


@dataclass(frozen=True)
class Recipient:
    user_id: uuid.UUID
    email: str
    display_name: str


async def gather_recipients(db: AsyncSession, league_id: uuid.UUID) -> list[Recipient]:
    """Current members of the club eligible for email: still a member
    (``removed_at`` null), account live (``deleted_at`` null), and notifications
    enabled. Returns plain data so callers can dispatch outside the DB session."""
    rows = await db.execute(
        select(User.id, User.email, User.display_name)
        .join(ClubMember, ClubMember.user_id == User.id)
        .where(
            ClubMember.club_id == league_id,
            ClubMember.removed_at.is_(None),
            User.deleted_at.is_(None),
            User.email_notifications.is_(True),
        )
    )
    return [Recipient(user_id=r[0], email=r[1], display_name=r[2]) for r in rows.all()]


async def organizer_recipient(db: AsyncSession, club: Club) -> list[Recipient]:
    """The organizer as a recipient, or empty if the club has no organizer
    (hard-purged) or the organizer has email notifications off. Shared by the
    API path and the deadline job — anything that must reach only the
    organizer, never the whole club (e.g. an empty-mix nudge, MYS-145; a
    themeless-next-mix nudge, MYS-211)."""
    if club.organizer_id is None:
        return []
    recipients = await gather_recipients(db, club.id)
    return [r for r in recipients if r.user_id == club.organizer_id]


def _mix_label(mix_: Mix) -> str:
    """A human label for the mystery mix: theme if set, else 'Mystery Mix N'."""
    if mix_.theme:
        return f"Mystery Mix {mix_.mix_number}: {mix_.theme}"
    return f"Mystery Mix {mix_.mix_number}"


def _format_deadline(deadline: datetime) -> str:
    """A compact absolute-UTC deadline for email copy, e.g. 'Jul 5, 21:00 UTC'.
    Avoids the platform-specific ``%-d`` so it formats identically everywhere."""
    d = deadline.astimezone(timezone.utc)
    return f"{d.strftime('%b')} {d.day}, {d.strftime('%H:%M')} UTC"


def _subject_and_body(event: MixEvent, club: Club, mix_: Mix, club_url: str) -> tuple[str, str]:
    """Return (subject, body_html_fragment) for an event, sans the unsubscribe
    footer (added per-recipient)."""
    label = _mix_label(mix_)
    link = f'<a href="{club_url}">Go to {club.name} →</a>'
    if event == "submission_open":
        # MYS-162: include the concrete deadline when the mix has one stamped.
        by = (
            f" Submit by {_format_deadline(mix_.submission_deadline)}."
            if mix_.submission_deadline is not None
            else ""
        )
        return (
            f"{club.name} — {label} is open for submissions",
            f"<p><strong>{label}</strong> is open in <strong>{club.name}</strong>. "
            f"Pick your song and get it in.{by} {link}</p>",
        )
    if event == "voting_open":
        # MYS-162: include the concrete voting deadline when stamped.
        by = (
            f" Vote by {_format_deadline(mix_.voting_deadline)}."
            if mix_.voting_deadline is not None
            else ""
        )
        return (
            f"{club.name} — voting is open for {label}",
            f"<p>Submissions are in for <strong>{label}</strong> in "
            f"<strong>{club.name}</strong>. Listen to the mix and cast your votes.{by} "
            f"{link}</p>",
        )
    if event == "mix_closed":
        return (
            f"{club.name} — {label} results are in",
            f"<p><strong>{label}</strong> in <strong>{club.name}</strong> has closed. "
            f"The results and reveal are ready — see who picked what. {link}</p>",
        )
    if event == "voting_extended":
        # MYS-180: mix_.voting_deadline is always set by the time this fires —
        # the caller only reaches here from an already-open_voting mix.
        by = _format_deadline(mix_.voting_deadline) if mix_.voting_deadline else ""
        return (
            f"{club.name} — voting extended for {label}",
            f"<p>Voting for <strong>{label}</strong> in <strong>{club.name}</strong> has been "
            f"extended. New deadline: {by}. {link}</p>",
        )
    if event == "needs_theme":
        return (
            f"{club.name} — {label} needs a theme before it can open",
            f"<p><strong>{label}</strong> in <strong>{club.name}</strong> was next in line to "
            f"open, but it has no theme yet — mixes can't open without one. Set a theme, "
            f"then open it yourself whenever you're ready. {link}</p>",
        )
    # club_complete
    return (
        f"{club.name} — that's a wrap",
        f"<p><strong>{club.name}</strong> has wrapped after its final mystery mix. "
        f"Check the standings for the final results. {link}</p>",
    )


def _club_url(settings: Settings, league_id: uuid.UUID) -> str:
    return f"{settings.app_base_url.rstrip('/')}/clubs/{league_id}"


def _unsubscribe_url(settings: Settings, user_id: uuid.UUID) -> str:
    base = (settings.api_base_url or settings.app_base_url).rstrip("/")
    token = create_unsubscribe_token(user_id)
    return f"{base}/api/v1/notifications/unsubscribe?token={token}"


def _wrap_html(body: str, unsubscribe_url: str) -> str:
    return (
        f"{body}"
        f'<p style="color:#8A8680;font-size:12px;margin-top:24px">'
        f"You're receiving this because you're in this club on MysteryMixClub. "
        f'<a href="{unsubscribe_url}">Unsubscribe from these emails</a>.</p>'
    )


def _html_and_headers(
    settings: Settings, user_id: uuid.UUID, body: str
) -> tuple[str, dict[str, str]]:
    """Wrap a body with a per-recipient unsubscribe footer + one-click headers.

    List-Unsubscribe(+Post) surface Gmail/Yahoo's native one-click unsubscribe and
    are part of their bulk-sender deliverability rules. Shared by every dispatch
    path so the API and job emails are byte-for-byte consistent."""
    url = _unsubscribe_url(settings, user_id)
    html = _wrap_html(body, url)
    headers = {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    return html, headers


def _send_direct(
    sender: EmailSender,
    settings: Settings,
    recipients: list[Recipient],
    subject: str,
    body: str,
) -> None:
    """Synchronously send one email per recipient (job path — no BackgroundTasks).

    Best-effort: :func:`_safe_send` swallows per-recipient failures so one bad
    address can't stop the rest. No-ops on an empty recipient list."""
    for r in recipients:
        html, headers = _html_and_headers(settings, r.user_id, body)
        _safe_send(sender, r.email, subject, html, headers)


def queue_mix_event(
    background_tasks: BackgroundTasks,
    sender: EmailSender,
    settings: Settings,
    recipients: list[Recipient],
    club: Club,
    mix_: Mix,
    event: MixEvent,
) -> None:
    """Schedule one notification email per recipient for ``event``.

    Best-effort: each send runs as its own background task wrapped so one failure
    can't take down the others or the request. No-ops when there are no
    recipients (e.g. everyone unsubscribed)."""
    if not recipients:
        return
    club_url = _club_url(settings, club.id)
    subject, body = _subject_and_body(event, club, mix_, club_url)
    for r in recipients:
        html, headers = _html_and_headers(settings, r.user_id, body)
        background_tasks.add_task(_safe_send, sender, r.email, subject, html, headers)


def send_mix_event(
    sender: EmailSender,
    settings: Settings,
    recipients: list[Recipient],
    club: Club,
    mix_: Mix,
    event: MixEvent,
) -> None:
    """Synchronous twin of :func:`queue_mix_event` for the deadline job.

    Same subject/body as the API path; sends inline instead of via a background
    task. No-ops when there are no recipients."""
    if not recipients:
        return
    club_url = _club_url(settings, club.id)
    subject, body = _subject_and_body(event, club, mix_, club_url)
    _send_direct(sender, settings, recipients, subject, body)


def send_deadline_warning(
    sender: EmailSender,
    settings: Settings,
    recipients: list[Recipient],
    club: Club,
    mix_: Mix,
    phase: DeadlinePhase,
) -> None:
    """Send the "about 12 hours left" warning to the outstanding actors (MYS-162).

    The caller (deadline job) has already filtered ``recipients`` to exactly those
    who still need to act this phase. No-ops on an empty list."""
    if not recipients:
        return
    club_url = _club_url(settings, club.id)
    label = _mix_label(mix_)
    link = f'<a href="{club_url}">Go to {club.name} →</a>'
    if phase == "submission":
        subject = f"{club.name} — about 12 hours left to submit"
        action = f"submit to <strong>{label}</strong>"
    else:
        subject = f"{club.name} — about 12 hours left to vote"
        action = f"vote in <strong>{label}</strong>"
    body = (
        f"<p>You have about 12 hours to {action} in <strong>{club.name}</strong>. "
        f"Whatever is in by the deadline counts. {link}</p>"
    )
    _send_direct(sender, settings, recipients, subject, body)


def send_empty_mix_notice(
    sender: EmailSender,
    settings: Settings,
    recipients: list[Recipient],
    club: Club,
    mix_: Mix,
) -> None:
    """Tell the organizer a submission deadline passed with zero songs (MYS-145).

    The mix is left open (it never auto-advances empty); the organizer can
    extend the deadline or advance it manually. ``recipients`` is the organizer
    only, already filtered for the email-notifications preference. No-ops when the
    organizer has notifications off (empty list)."""
    if not recipients:
        return
    club_url = _club_url(settings, club.id)
    label = _mix_label(mix_)
    link = f'<a href="{club_url}">Go to {club.name} →</a>'
    subject = f"{club.name} — {label} closed with no submissions"
    body = (
        f"<p>The submission deadline for <strong>{label}</strong> in "
        f"<strong>{club.name}</strong> passed with no songs submitted. You can extend the "
        f"deadline or advance the mix manually. {link}</p>"
    )
    _send_direct(sender, settings, recipients, subject, body)


def send_waitlist_invite(
    sender: EmailSender, settings: Settings, email: str, invite_url: str
) -> None:
    """Tell a waitlist entry their invite is ready (MYS-215, temporary).

    Sent to an address with no User row yet — unlike every other notification
    here, there's no notification preference to check and no unsubscribe
    footer to attach (same reasoning as the magic-link email)."""
    subject = "you're off the mysterymixclub waitlist"
    body = (
        "<p>a spot opened up, and you're in. here's your invite link:</p>"
        f'<p><a href="{invite_url}">join mysterymixclub →</a></p>'
        "<p>it expires in 48 hours.</p>"
    )
    _safe_send(sender, email, subject, body)


def queue_club_joined(
    background_tasks: BackgroundTasks,
    sender: EmailSender,
    settings: Settings,
    email: str,
    user_id: uuid.UUID,
    league_id: uuid.UUID,
    league_name: str,
) -> None:
    """Schedule a welcome email for a user who just joined (or rejoined) a club."""
    url = _club_url(settings, league_id)
    subject = f"You've joined {league_name}"
    body = (
        f"<p>You're in! You've joined <strong>{league_name}</strong>. "
        f'<a href="{url}">View {league_name} →</a></p>'
    )
    html, headers = _html_and_headers(settings, user_id, body)
    background_tasks.add_task(_safe_send, sender, email, subject, html, headers)


def _safe_send(
    sender: EmailSender, email: str, subject: str, html: str, headers: dict[str, str] | None = None
) -> None:
    try:
        sender.send(email, subject, html, headers)
    except Exception:  # noqa: BLE001 — never let a mail failure escape the task
        logger.exception("failed to send notification email to %s", email)
