"""Round-lifecycle email notifications (MYS-109).

Generalizes the magic-link mailer into per-event notifications fired when a
round changes state. Recipients are the league's current members who have email
notifications enabled; sending is best-effort and runs in a background task so a
slow or failing mail provider never blocks (or fails) the state-transition
request that triggered it.

The single entry point is :func:`queue_round_event` — the rounds route gathers
recipients while its DB session is open, then schedules delivery. When MYS-69
(auto-advance) lands it should call the same helper so there is one notification
path, not two.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_unsubscribe_token
from app.config import Settings
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.round import Round
from app.models.user import User
from app.services.email import EmailSender

logger = logging.getLogger("app.services.notifications")

# The lifecycle moments worth an email. Kept distinct from the raw round states
# so "the next round auto-opened" and "this round opened" can both map to a
# submission_open notification for their respective rounds.
RoundEvent = Literal["submission_open", "voting_open", "round_closed", "league_complete"]


@dataclass(frozen=True)
class Recipient:
    user_id: uuid.UUID
    email: str
    display_name: str


async def gather_recipients(db: AsyncSession, league_id: uuid.UUID) -> list[Recipient]:
    """Current members of the league eligible for email: still a member
    (``removed_at`` null), account live (``deleted_at`` null), and notifications
    enabled. Returns plain data so callers can dispatch outside the DB session."""
    rows = await db.execute(
        select(User.id, User.email, User.display_name)
        .join(LeagueMember, LeagueMember.user_id == User.id)
        .where(
            LeagueMember.league_id == league_id,
            LeagueMember.removed_at.is_(None),
            User.deleted_at.is_(None),
            User.email_notifications.is_(True),
        )
    )
    return [Recipient(user_id=r[0], email=r[1], display_name=r[2]) for r in rows.all()]


def _round_label(round_: Round) -> str:
    """A human label for the round: theme if set, else 'Round N'."""
    if round_.theme:
        return f"Round {round_.round_number}: {round_.theme}"
    return f"Round {round_.round_number}"


def _subject_and_body(event: RoundEvent, league: League, round_: Round) -> tuple[str, str]:
    """Return (subject, body_html_fragment) for an event, sans the unsubscribe
    footer (added per-recipient)."""
    label = _round_label(round_)
    if event == "submission_open":
        return (
            f"{league.name} — {label} is open for submissions",
            f"<p><strong>{label}</strong> is open in <strong>{league.name}</strong>. "
            "Pick your song and submit it before the deadline.</p>",
        )
    if event == "voting_open":
        return (
            f"{league.name} — voting is open for {label}",
            f"<p>Submissions are in for <strong>{label}</strong> in "
            f"<strong>{league.name}</strong>. Listen to the playlist and cast your votes.</p>",
        )
    if event == "round_closed":
        return (
            f"{league.name} — {label} results are in",
            f"<p><strong>{label}</strong> in <strong>{league.name}</strong> has closed. "
            "The results and reveal are ready — see who picked what.</p>",
        )
    # league_complete
    return (
        f"{league.name} — the league is complete",
        f"<p><strong>{league.name}</strong> has wrapped after its final round. "
        "Check the standings for the final results.</p>",
    )


def _unsubscribe_url(settings: Settings, user_id: uuid.UUID) -> str:
    base = (settings.api_base_url or settings.app_base_url).rstrip("/")
    token = create_unsubscribe_token(user_id)
    return f"{base}/api/v1/notifications/unsubscribe?token={token}"


def _wrap_html(body: str, unsubscribe_url: str) -> str:
    return (
        f"{body}"
        f'<p style="color:#8A8680;font-size:12px;margin-top:24px">'
        f"You're receiving this because you're in this MysteryMixClub league. "
        f'<a href="{unsubscribe_url}">Unsubscribe from these emails</a>.</p>'
    )


def queue_round_event(
    background_tasks: BackgroundTasks,
    sender: EmailSender,
    settings: Settings,
    recipients: list[Recipient],
    league: League,
    round_: Round,
    event: RoundEvent,
) -> None:
    """Schedule one notification email per recipient for ``event``.

    Best-effort: each send runs as its own background task wrapped so one failure
    can't take down the others or the request. No-ops when there are no
    recipients (e.g. everyone unsubscribed)."""
    if not recipients:
        return
    subject, body = _subject_and_body(event, league, round_)
    for r in recipients:
        html = _wrap_html(body, _unsubscribe_url(settings, r.user_id))
        background_tasks.add_task(_safe_send, sender, r.email, subject, html)


def _safe_send(sender: EmailSender, email: str, subject: str, html: str) -> None:
    try:
        sender.send(email, subject, html)
    except Exception:  # noqa: BLE001 — never let a mail failure escape the task
        logger.exception("failed to send notification email to %s", email)
