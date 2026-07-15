"""Force-advance rounds past their deadline and send 12h warnings (MYS-145 / MYS-162).

A round closes on quorum OR a deadline, whichever comes first (epic MYS-158). The
API path handles quorum (auto-advance in votes.py); this scheduled job handles the
deadline. It is invoked by an external scheduler (systemd timer) as a standalone
process:

    python -m app.jobs.advance_rounds

It scans every live round (``open_submission`` / ``open_voting``) and processes
EACH in its own transaction, taking a ``SELECT … FOR UPDATE`` lock on the round
row and re-checking state + deadline under the lock — the same discipline as the
vote-cast auto-close, so the job never races a concurrent API transition.

Per locked round, the first matching branch wins:

1. Phase deadline is NULL  → stamp ``now + league window`` and stop (no email).
2. Deadline in the future  → if the phase window is > 12h, no warning has gone
   out yet, and the deadline is 1–12h away, warn the outstanding actors and stamp
   the per-phase warning marker.
3. Deadline passed, ``open_submission``, ZERO submissions → do NOT advance; email
   the organizer once (extend or advance manually) and stamp the notice. The round
   holds open indefinitely.
4. Deadline passed, ``open_submission``, ≥1 submission → advance to ``open_voting``.
5. Deadline passed, ``open_voting`` → close (zero votes still closes).

One round's failure is logged and skipped; the job exits nonzero only if the whole
run fails (e.g. the initial scan can't reach the database).
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.rounds import advance_round_state
from app.config import Settings, get_settings
from app.db.session import async_session_factory
from app.models.league import League
from app.models.round import Round
from app.models.submission import Submission
from app.models.vote import Vote
from app.services.email import EmailSender, build_email_sender
from app.services.notifications import (
    DeadlinePhase,
    Recipient,
    gather_recipients,
    send_deadline_warning,
    send_empty_round_notice,
    send_round_event,
)
from app.services.spotify_client import SpotifyClient, get_spotify_client
from app.services.spotify_playlist_generation import try_auto_generate_playlist

logger = logging.getLogger("app.jobs.advance_rounds")

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
    db: AsyncSession, league: League, round_: Round, phase: DeadlinePhase
) -> list[Recipient]:
    """The subset of email-enabled members who still need to act this phase.

    Submission: members whose distinct-song count in the round is below the
    league's ``songs_per_submission`` cap (zero included). Voting: playing
    submitters (a member with a ``playing`` submission) who have not voted."""
    recipients = await gather_recipients(db, league.id)
    if phase == "submission":
        rows = await db.execute(
            select(Submission.user_id, func.count())
            .where(Submission.round_id == round_.id)
            .group_by(Submission.user_id)
        )
        counts = {user_id: count for user_id, count in rows.all()}
        cap = league.songs_per_submission
        return [r for r in recipients if counts.get(r.user_id, 0) < cap]
    playing_ids = set(
        await db.scalars(
            select(Submission.user_id)
            .where(Submission.round_id == round_.id, Submission.participation_mode == "playing")
            .distinct()
        )
    )
    voter_ids = set(
        await db.scalars(select(Vote.voter_id).where(Vote.round_id == round_.id).distinct())
    )
    outstanding = playing_ids - voter_ids
    return [r for r in recipients if r.user_id in outstanding]


async def _organizer_recipient(db: AsyncSession, league: League) -> list[Recipient]:
    """The organizer as a recipient, or empty if the league has no organizer
    (hard-purged) or the organizer has email notifications off."""
    if league.organizer_id is None:
        return []
    recipients = await gather_recipients(db, league.id)
    return [r for r in recipients if r.user_id == league.organizer_id]


async def _process_round(
    db: AsyncSession,
    round_id: uuid.UUID,
    now: datetime,
    settings: Settings,
    sender: EmailSender,
    client: SpotifyClient,
    report: AdvanceReport,
) -> None:
    """Process a single round under a row lock, in the caller's transaction.

    Commits its own mutation before sending any email (so a mail failure can never
    re-fire an already-recorded advance/warning). ``expire_on_commit`` is off on
    the session factory, so the ORM objects stay readable for the post-commit send.
    """
    # Lock the round row and re-read its state under the lock, defeating a race
    # with a concurrent API transition (mirrors the vote-cast auto-close).
    round_ = await db.scalar(
        select(Round)
        .where(Round.id == round_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if round_ is None or round_.state not in _LIVE_STATES:
        report.skipped += 1
        return
    league = await db.scalar(select(League).where(League.id == round_.league_id))
    if league is None:
        report.skipped += 1
        return

    is_submission = round_.state == "open_submission"
    deadline = round_.submission_deadline if is_submission else round_.voting_deadline
    window_hours = league.submission_window_hours if is_submission else league.voting_window_hours

    # Branch 1: no deadline yet — stamp it from the league window and stop.
    if deadline is None:
        stamped = now + timedelta(hours=window_hours)
        if is_submission:
            round_.submission_deadline = stamped
        else:
            round_.voting_deadline = stamped
        await db.commit()
        report.stamped += 1
        return

    # Branch 2: deadline still ahead — maybe send the 12h warning.
    if deadline > now:
        warning_sent = (
            round_.submission_warning_sent_at if is_submission else round_.voting_warning_sent_at
        )
        remaining = deadline - now
        if (
            window_hours > _WARNING_MIN_WINDOW_HOURS
            and warning_sent is None
            and _WARNING_LEAD_MIN <= remaining <= _WARNING_LEAD_MAX
        ):
            phase: DeadlinePhase = "submission" if is_submission else "voting"
            recipients = await _warning_recipients(db, league, round_, phase)
            if is_submission:
                round_.submission_warning_sent_at = now
            else:
                round_.voting_warning_sent_at = now
            await db.commit()
            send_deadline_warning(sender, settings, recipients, league, round_, phase)
            report.warned += 1
        return

    # Deadline has passed (deadline <= now).
    if is_submission:
        submission_count = await db.scalar(
            select(func.count()).select_from(Submission).where(Submission.round_id == round_.id)
        )
        # Branch 3: nobody submitted — never auto-advance an empty round; nudge the
        # organizer once and leave the round open indefinitely.
        if (submission_count or 0) == 0:
            if round_.empty_round_notice_sent_at is None:
                recipients = await _organizer_recipient(db, league)
                round_.empty_round_notice_sent_at = now
                await db.commit()
                send_empty_round_notice(sender, settings, recipients, league, round_)
                report.empty_notices += 1
            else:
                report.skipped += 1
            return
        # Branch 4: submissions are in — advance to voting.
        events = await advance_round_state(round_, league, "open_voting", db)
        recipients = await gather_recipients(db, league.id)
        await db.commit()
        for event_round, event in events:
            send_round_event(sender, settings, recipients, league, event_round, event)
        # Auto-generate the shared-account Spotify playlist the moment voting
        # opens (MYS-176) — no admin click needed. Best-effort: never raises.
        if any(event == "voting_open" for _, event in events):
            await try_auto_generate_playlist(round_id, round_, league, db, client, settings)
        report.advanced_to_voting += 1
        return

    # Branch 5: voting deadline passed — close the round (zero votes still closes).
    events = await advance_round_state(round_, league, "closed", db)
    recipients = await gather_recipients(db, league.id)
    await db.commit()
    for event_round, event in events:
        send_round_event(sender, settings, recipients, league, event_round, event)
    report.closed += 1


async def advance_due_rounds(
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
    sender: EmailSender | None = None,
    client: SpotifyClient | None = None,
) -> AdvanceReport:
    """Scan live rounds and process each in its own locked transaction.

    Returns an :class:`AdvanceReport`. A single round's failure is logged and
    counted, never fatal; only a failure of the initial scan propagates."""
    settings = settings or get_settings()
    sender = sender or build_email_sender(settings)
    client = client or get_spotify_client()
    now = now or datetime.now(timezone.utc)

    # Read-only scan in its own short-lived session; each round is then locked and
    # processed in a fresh transaction so one round's rollback can't touch another.
    async with async_session_factory() as db:
        round_ids = list(await db.scalars(select(Round.id).where(Round.state.in_(_LIVE_STATES))))

    report = AdvanceReport()
    for round_id in round_ids:
        try:
            async with async_session_factory() as db:
                await _process_round(db, round_id, now, settings, sender, client, report)
        except Exception:  # noqa: BLE001 — isolate one round's failure from the rest
            logger.exception("advance_rounds: failed processing round %s", round_id)
            report.errors += 1
    return report


async def _run() -> None:
    report = await advance_due_rounds()
    logger.info(
        "advance_rounds: stamped=%d warned=%d empty_notices=%d advanced=%d closed=%d "
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
        f"advance_rounds: stamped={report.stamped} warned={report.warned} "
        f"empty_notices={report.empty_notices} advanced={report.advanced_to_voting} "
        f"closed={report.closed} skipped={report.skipped} errors={report.errors}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())
