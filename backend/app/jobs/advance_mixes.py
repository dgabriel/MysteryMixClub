"""Force-advance mixes past their deadline and send 12h warnings (MYS-145 / MYS-162).

A mix closes on quorum OR a deadline, whichever comes first (epic MYS-158). The
API path handles quorum (auto-advance in votes.py); this scheduled job handles the
deadline. It is invoked by an external scheduler (systemd timer) as a standalone
process:

    python -m app.jobs.advance_mixes

It scans every live mix (``open_submission`` / ``open_voting``) and processes
EACH in its own transaction, taking a ``SELECT … FOR UPDATE`` lock on the mix
row and re-checking state + deadline under the lock — the same discipline as the
vote-cast auto-close, so the job never races a concurrent API transition.

Per locked mix, the first matching branch wins:

1. Phase deadline is NULL  → stamp ``now + club window`` and stop (no email).
2. Deadline in the future  → if the phase window is > 12h, no warning has gone
   out yet, and the deadline is 1–12h away, warn the outstanding actors and stamp
   the per-phase warning marker.
3. Deadline passed, ``open_submission``, ZERO submissions → do NOT advance; email
   the organizer once (extend or advance manually) and stamp the notice. The mix
   holds open indefinitely.
4. Deadline passed, ``open_submission``, ≥1 submission → advance to ``open_voting``.
5. Deadline passed, ``open_voting`` → close (zero votes still closes).

One mix's failure is logged and skipped; the job exits nonzero only if the whole
run fails (e.g. the initial scan can't reach the database).
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.mixes import advance_mix_state
from app.config import Settings, get_settings
from app.db.session import async_session_factory
from app.models.club import Club
from app.models.mix import Mix
from app.models.submission import Submission
from app.models.vote import Vote
from app.services.email import EmailSender, build_email_sender
from app.services.notifications import (
    DeadlinePhase,
    Recipient,
    gather_recipients,
    organizer_recipient,
    send_deadline_warning,
    send_empty_mix_notice,
    send_mix_event,
)
from app.services.spotify_client import SpotifyClient, get_spotify_client
from app.services.spotify_playlist_generation import try_auto_generate_playlist

logger = logging.getLogger("app.jobs.advance_mixes")

# The live states this job acts on.
_LIVE_STATES = ("open_submission", "open_voting")
# Warning fires only when the phase window is longer than the 12h lead time —
# there's no "12 hours left" to announce for a window that short.
_WARNING_MIN_WINDOW_HOURS = 12
# Fire the warning once the deadline is between 1 and 12 hours away.
_WARNING_LEAD_MIN = timedelta(hours=1)
_WARNING_LEAD_MAX = timedelta(hours=12)


@dataclass
class AdvanceReport:
    """Tally of what the run did, for the log line and for tests."""

    stamped: int = 0
    warned: int = 0
    empty_notices: int = 0
    advanced_to_voting: int = 0
    closed: int = 0
    skipped: int = 0
    errors: int = 0


async def _warning_recipients(
    db: AsyncSession, club: Club, mix_: Mix, phase: DeadlinePhase
) -> list[Recipient]:
    """The subset of email-enabled members who still need to act this phase.

    Submission: members whose distinct-song count in the mix is below the
    club's ``songs_per_submission`` cap (zero included). Voting: playing
    submitters (a member with a ``playing`` submission) who have not voted."""
    recipients = await gather_recipients(db, club.id)
    if phase == "submission":
        rows = await db.execute(
            select(Submission.user_id, func.count())
            .where(Submission.mix_id == mix_.id)
            .group_by(Submission.user_id)
        )
        counts = {user_id: count for user_id, count in rows.all()}
        cap = club.songs_per_submission
        return [r for r in recipients if counts.get(r.user_id, 0) < cap]
    playing_ids = set(
        await db.scalars(
            select(Submission.user_id)
            .where(Submission.mix_id == mix_.id, Submission.participation_mode == "playing")
            .distinct()
        )
    )
    voter_ids = set(
        await db.scalars(select(Vote.voter_id).where(Vote.mix_id == mix_.id).distinct())
    )
    outstanding = playing_ids - voter_ids
    return [r for r in recipients if r.user_id in outstanding]


async def _process_mix(
    db: AsyncSession,
    mix_id: uuid.UUID,
    now: datetime,
    settings: Settings,
    sender: EmailSender,
    client: SpotifyClient,
    report: AdvanceReport,
) -> None:
    """Process a single mix under a row lock, in the caller's transaction.

    Commits its own mutation before sending any email (so a mail failure can never
    re-fire an already-recorded advance/warning). ``expire_on_commit`` is off on
    the session factory, so the ORM objects stay readable for the post-commit send.
    """
    # Lock the mix row and re-read its state under the lock, defeating a race
    # with a concurrent API transition (mirrors the vote-cast auto-close).
    mix_ = await db.scalar(
        select(Mix)
        .where(Mix.id == mix_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if mix_ is None or mix_.state not in _LIVE_STATES:
        report.skipped += 1
        return
    club = await db.scalar(select(Club).where(Club.id == mix_.club_id))
    if club is None:
        report.skipped += 1
        return

    is_submission = mix_.state == "open_submission"
    deadline = mix_.submission_deadline if is_submission else mix_.voting_deadline
    window_hours = club.submission_window_hours if is_submission else club.voting_window_hours

    # Branch 1: no deadline yet — stamp it from the club window and stop.
    if deadline is None:
        stamped = now + timedelta(hours=window_hours)
        if is_submission:
            mix_.submission_deadline = stamped
        else:
            mix_.voting_deadline = stamped
        await db.commit()
        report.stamped += 1
        return

    # Branch 2: deadline still ahead — maybe send the 12h warning.
    if deadline > now:
        warning_sent = (
            mix_.submission_warning_sent_at if is_submission else mix_.voting_warning_sent_at
        )
        remaining = deadline - now
        if (
            window_hours > _WARNING_MIN_WINDOW_HOURS
            and warning_sent is None
            and _WARNING_LEAD_MIN <= remaining <= _WARNING_LEAD_MAX
        ):
            phase: DeadlinePhase = "submission" if is_submission else "voting"
            recipients = await _warning_recipients(db, club, mix_, phase)
            if is_submission:
                mix_.submission_warning_sent_at = now
            else:
                mix_.voting_warning_sent_at = now
            await db.commit()
            send_deadline_warning(sender, settings, recipients, club, mix_, phase)
            report.warned += 1
        return

    # Deadline has passed (deadline <= now).
    if is_submission:
        submission_count = await db.scalar(
            select(func.count()).select_from(Submission).where(Submission.mix_id == mix_.id)
        )
        # Branch 3: nobody submitted — never auto-advance an empty mix; nudge the
        # organizer once and leave the mix open indefinitely.
        if (submission_count or 0) == 0:
            if mix_.empty_round_notice_sent_at is None:
                recipients = await organizer_recipient(db, club)
                mix_.empty_round_notice_sent_at = now
                await db.commit()
                send_empty_mix_notice(sender, settings, recipients, club, mix_)
                report.empty_notices += 1
            else:
                report.skipped += 1
            return
        # Branch 4: submissions are in — advance to voting.
        events = await advance_mix_state(mix_, club, "open_voting", db)
        recipients = await gather_recipients(db, club.id)
        await db.commit()
        for event_mix, event in events:
            send_mix_event(sender, settings, recipients, club, event_mix, event)
        # Auto-generate the shared-account Spotify playlist the moment voting
        # opens (MYS-176) — no admin click needed. Best-effort: never raises.
        if any(event == "voting_open" for _, event in events):
            await try_auto_generate_playlist(mix_id, mix_, club, db, client, settings)
        report.advanced_to_voting += 1
        return

    # Branch 5: voting deadline passed — close the mix (zero votes still closes).
    events = await advance_mix_state(mix_, club, "closed", db)
    recipients = await gather_recipients(db, club.id)
    # needs_theme (MYS-211) is organizer-only, never the whole club.
    theme_notice_recipients = (
        await organizer_recipient(db, club)
        if any(event == "needs_theme" for _, event in events)
        else []
    )
    await db.commit()
    for event_mix, event in events:
        if event == "needs_theme":
            send_mix_event(sender, settings, theme_notice_recipients, club, event_mix, event)
        else:
            send_mix_event(sender, settings, recipients, club, event_mix, event)
    report.closed += 1


async def advance_due_mixes(
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
    sender: EmailSender | None = None,
    client: SpotifyClient | None = None,
) -> AdvanceReport:
    """Scan live mixes and process each in its own locked transaction.

    Returns an :class:`AdvanceReport`. A single mix's failure is logged and
    counted, never fatal; only a failure of the initial scan propagates."""
    settings = settings or get_settings()
    sender = sender or build_email_sender(settings)
    client = client or get_spotify_client()
    now = now or datetime.now(timezone.utc)

    # Read-only scan in its own short-lived session; each mix is then locked and
    # processed in a fresh transaction so one mix's rollback can't touch another.
    async with async_session_factory() as db:
        mix_ids = list(await db.scalars(select(Mix.id).where(Mix.state.in_(_LIVE_STATES))))

    report = AdvanceReport()
    for mix_id in mix_ids:
        try:
            async with async_session_factory() as db:
                await _process_mix(db, mix_id, now, settings, sender, client, report)
        except Exception:  # noqa: BLE001 — isolate one mix's failure from the rest
            logger.exception("advance_mixes: failed processing mix %s", mix_id)
            report.errors += 1
    return report


async def _run() -> None:
    report = await advance_due_mixes()
    logger.info(
        "advance_mixes: stamped=%d warned=%d empty_notices=%d advanced=%d closed=%d "
        "skipped=%d errors=%d",
        report.stamped,
        report.warned,
        report.empty_notices,
        report.advanced_to_voting,
        report.closed,
        report.skipped,
        report.errors,
    )
    print(
        f"advance_mixes: stamped={report.stamped} warned={report.warned} "
        f"empty_notices={report.empty_notices} advanced={report.advanced_to_voting} "
        f"closed={report.closed} skipped={report.skipped} errors={report.errors}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())
