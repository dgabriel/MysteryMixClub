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
   Otherwise, push-only nudges (MysteryMixClub-bfqo), at most one per run: the
   08:00 "due today" nudge (club timezone, or US Central for a club that never chose one), the halfway nudge, and, in submission,
   the "3 or fewer left" nudge. See :func:`_send_due_nudge`.
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
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote
from app.services.apple_push_token import ApplePushTokenService, build_apple_push_token_service
from app.services.deadline_scheduling import compute_phase_deadline
from app.services.email import EmailSender, build_email_sender
from app.services import nudge_timing
from app.services.notifications import (
    DeadlinePhase,
    Recipient,
    gather_recipients,
    organizer_recipient,
    send_deadline_warning,
    send_empty_mix_notice,
    send_mix_event,
)
from app.services.playlist_jobs import enqueue_playlist_job
from app.services.push_notifications import (
    NudgeKind,
    PushRecipient,
    gather_push_deadline_recipients,
    gather_push_recipients,
    organizer_push_recipients,
    send_push_event,
    send_push_nudge,
    send_push_reminder,
)

logger = logging.getLogger("app.jobs.advance_mixes")

# The live states this job acts on.
_LIVE_STATES = ("open_submission", "open_voting")
# Warning fires only when the phase window is longer than the 12h lead time —
# there's no "12 hours left" to announce for a window that short.
_WARNING_MIN_WINDOW_HOURS = 12
# Fire the warning once the deadline is between 1 and 12 hours away.
_WARNING_LEAD_MIN = timedelta(hours=1)
_WARNING_LEAD_MAX = timedelta(hours=12)

# Push's own additional far-out reminder (MysteryMixClub-4vii.26, IOS-04):
# fires once more at ~24h before a deadline, on top of (not instead of) the
# same 1-12h window email already uses -- Dawn confirmed both cadences.
# Requires a longer window than the 1-12h warning does (there's no "24 hours
# left" worth announcing for a phase shorter than a day), and uses its own
# sent-at columns since it's a genuinely separate notice, not a duplicate of
# the 1-12h one.
_PUSH_FAR_REMINDER_MIN_WINDOW_HOURS = 24
_PUSH_FAR_REMINDER_LEAD_MIN = timedelta(hours=23)
_PUSH_FAR_REMINDER_LEAD_MAX = timedelta(hours=24)

# The submission-phase "last few" nudge fires once when this many members (or
# fewer, but at least one) still have not submitted.
_LAST_FEW_MAX = 3


@dataclass
class AdvanceReport:
    """Tally of what the run did, for the log line and for tests."""

    stamped: int = 0
    warned: int = 0
    pushed_far: int = 0
    nudged: int = 0
    empty_notices: int = 0
    advanced_to_voting: int = 0
    closed: int = 0
    skipped: int = 0
    errors: int = 0


async def _outstanding_user_ids(
    db: AsyncSession, club: Club, mix_: Mix, phase: DeadlinePhase
) -> set[uuid.UUID]:
    """Who still needs to act this phase, by user id -- shared by the email
    and push warning-recipient queries (MysteryMixClub-4vii.26) so the two
    channels can never disagree about who's outstanding.

    Submission: members whose distinct-song count in the mix is below the
    club's ``songs_per_submission`` cap (zero included). Voting: playing
    submitters (a member with a ``playing`` submission) who have not voted."""
    if phase == "submission":
        rows = await db.execute(
            select(Submission.user_id, func.count())
            .where(Submission.mix_id == mix_.id)
            .group_by(Submission.user_id)
        )
        counts = {user_id: count for user_id, count in rows.all()}
        cap = club.songs_per_submission
        # Every current member, NOT just those with email on: "who still needs
        # to act" is a fact about the club, and each channel then intersects it
        # with its own opted-in recipients (a member with email off and push on
        # is still outstanding, and still counts in a head count).
        members = await db.scalars(
            select(ClubMember.user_id)
            .join(User, User.id == ClubMember.user_id)
            .where(
                ClubMember.club_id == club.id,
                ClubMember.removed_at.is_(None),
                User.deleted_at.is_(None),
            )
        )
        return {user_id for user_id in members if counts.get(user_id, 0) < cap}
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
    return playing_ids - voter_ids


async def _warning_recipients(
    db: AsyncSession, club: Club, mix_: Mix, phase: DeadlinePhase
) -> list[Recipient]:
    """The subset of email-enabled members who still need to act this phase."""
    recipients = await gather_recipients(db, club.id)
    outstanding = await _outstanding_user_ids(db, club, mix_, phase)
    return [r for r in recipients if r.user_id in outstanding]


async def _warning_push_recipients(
    db: AsyncSession, club: Club, mix_: Mix, phase: DeadlinePhase
) -> list[PushRecipient]:
    """Push counterpart of :func:`_warning_recipients` -- same outstanding-
    action set, gated on ``push_deadline_reminders_enabled`` instead of
    ``email_notifications`` (:func:`gather_push_deadline_recipients`), one
    row per device. Shared by both the 1-12h and the ~24h push reminder."""
    recipients = await gather_push_deadline_recipients(db, club.id)
    outstanding = await _outstanding_user_ids(db, club, mix_, phase)
    return [r for r in recipients if r.user_id in outstanding]


# The once-per-phase marker column for each time-pinned nudge, by phase.
_NUDGE_MARKERS: dict[tuple[str, bool], str] = {
    ("halfway", True): "push_submission_halfway_sent_at",
    ("halfway", False): "push_voting_halfway_sent_at",
    ("due_morning", True): "push_submission_due_morning_sent_at",
    ("due_morning", False): "push_voting_due_morning_sent_at",
}


def _sent_marker(mix_: Mix, kind: str, is_submission: bool) -> datetime | None:
    value: datetime | None = getattr(mix_, _NUDGE_MARKERS[(kind, is_submission)])
    return value


def _stamp_marker(mix_: Mix, kind: str, is_submission: bool, now: datetime) -> None:
    setattr(mix_, _NUDGE_MARKERS[(kind, is_submission)], now)


async def _send_due_nudge(
    db: AsyncSession,
    club: Club,
    mix_: Mix,
    phase: DeadlinePhase,
    now: datetime,
    deadline: datetime,
    window_hours: int,
    settings: Settings,
    push_token_service: ApplePushTokenService,
    report: AdvanceReport,
) -> None:
    """Send at most one of the push-only nudges (MysteryMixClub-bfqo) for a live
    mix whose deadline is still ahead. Each goes only to members who still
    need to act and have "push: reminders" on, and fires once per phase.

    Priority: the 08:00 "due today" nudge, then halfway, then (submission only)
    the "3 or fewer left" nudge. Doing one per run keeps a single job pass from
    stacking pushes on a phone; the others are still due on the next pass (the
    15-minute timer) unless their moment has lapsed.

    A time-pinned nudge that lands within an hour of an existing reminder to the
    same audience (12h warning, ~24h push) or of the due-morning nudge is
    *suppressed*: its marker is stamped, nothing is sent, and the established
    notice stands alone. Stamped rather than skipped, so it cannot fire late.
    """
    is_submission = phase == "submission"
    opened = mix_.submission_opened_at if is_submission else mix_.voting_opened_at

    if opened is not None and opened < deadline:
        reminders = nudge_timing.scheduled_reminder_times(opened, deadline, window_hours)
        # "8am" needs a timezone the club actually chose. A weekly-anchor club
        # has one; a duration-mode club never sets one (its stored value is the
        # "UTC" placeholder, 03:00-04:00 in the US), so it gets US Central.
        due_tz = (
            club.timezone
            if club.deadline_mode == "weekly_anchor"
            else nudge_timing.DEFAULT_DUE_MORNING_TZ
        )
        due_morning = nudge_timing.due_morning_at(opened, deadline, due_tz)
        halfway = nudge_timing.halfway_at(opened, deadline)
        # A due-morning nudge that is itself suppressed sends nothing, so it
        # must not suppress halfway in turn.
        due_morning_sends = due_morning is not None and not nudge_timing.near_any(
            due_morning, reminders
        )

        candidates: list[tuple[NudgeKind, datetime, list[datetime]]] = []
        if due_morning is not None:
            candidates.append(("due_morning", due_morning, reminders))
        if halfway is not None:
            near = reminders + (
                [due_morning] if due_morning is not None and due_morning_sends else []
            )
            candidates.append(("halfway", halfway, near))

        for kind, moment, crowded_by in candidates:
            if _sent_marker(mix_, kind, is_submission) is not None:
                continue
            if not nudge_timing.is_due(moment, now):
                continue
            suppressed = nudge_timing.near_any(moment, crowded_by)
            recipients = [] if suppressed else await _warning_push_recipients(db, club, mix_, phase)
            _stamp_marker(mix_, kind, is_submission, now)
            await db.commit()
            if recipients:
                await send_push_nudge(
                    push_token_service,
                    settings,
                    recipients,
                    club,
                    mix_,
                    phase,
                    kind,
                )
                report.nudged += 1
            return

    if is_submission and mix_.push_submission_last_few_sent_at is None:
        outstanding = await _outstanding_user_ids(db, club, mix_, phase)
        if not 1 <= len(outstanding) <= _LAST_FEW_MAX:
            return
        # With nobody in yet, "only 3 left" is just the whole (small) club.
        has_submissions = await db.scalar(
            select(func.count()).select_from(Submission).where(Submission.mix_id == mix_.id)
        )
        if not has_submissions:
            return
        recipients = [
            r
            for r in await gather_push_deadline_recipients(db, club.id)
            if r.user_id in outstanding
        ]
        mix_.push_submission_last_few_sent_at = now
        await db.commit()
        if recipients:
            await send_push_nudge(
                push_token_service,
                settings,
                recipients,
                club,
                mix_,
                phase,
                "last_few",
                remaining=len(outstanding),
            )
            report.nudged += 1


async def _process_mix(
    db: AsyncSession,
    mix_id: uuid.UUID,
    now: datetime,
    settings: Settings,
    sender: EmailSender,
    push_token_service: ApplePushTokenService,
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

    # Branch 1: no deadline yet — stamp it from the club's deadline config and stop.
    if deadline is None:
        stamped = compute_phase_deadline(club, "submission" if is_submission else "voting", now)
        if is_submission:
            mix_.submission_deadline = stamped
        else:
            mix_.voting_deadline = stamped
        await db.commit()
        report.stamped += 1
        return

    # Branch 2: deadline still ahead — maybe send the 12h warning, and/or
    # push's own additional ~24h-out reminder (independent checks: different
    # windows, different sent-at columns, both can fire across a mix's life,
    # never on the same run since the windows don't overlap).
    if deadline > now:
        phase: DeadlinePhase = "submission" if is_submission else "voting"
        remaining = deadline - now

        warning_sent = (
            mix_.submission_warning_sent_at if is_submission else mix_.voting_warning_sent_at
        )
        if (
            window_hours > _WARNING_MIN_WINDOW_HOURS
            and warning_sent is None
            and _WARNING_LEAD_MIN <= remaining <= _WARNING_LEAD_MAX
        ):
            recipients = await _warning_recipients(db, club, mix_, phase)
            push_recipients = await _warning_push_recipients(db, club, mix_, phase)
            if is_submission:
                mix_.submission_warning_sent_at = now
            else:
                mix_.voting_warning_sent_at = now
            await db.commit()
            send_deadline_warning(sender, settings, recipients, club, mix_, phase)
            await send_push_reminder(
                push_token_service, settings, push_recipients, club, mix_, phase, far=False
            )
            report.warned += 1
            return

        far_reminder_sent = (
            mix_.push_submission_reminder_sent_at
            if is_submission
            else mix_.push_voting_reminder_sent_at
        )
        if (
            window_hours > _PUSH_FAR_REMINDER_MIN_WINDOW_HOURS
            and far_reminder_sent is None
            and _PUSH_FAR_REMINDER_LEAD_MIN <= remaining <= _PUSH_FAR_REMINDER_LEAD_MAX
        ):
            push_recipients = await _warning_push_recipients(db, club, mix_, phase)
            if is_submission:
                mix_.push_submission_reminder_sent_at = now
            else:
                mix_.push_voting_reminder_sent_at = now
            await db.commit()
            await send_push_reminder(
                push_token_service, settings, push_recipients, club, mix_, phase, far=True
            )
            report.pushed_far += 1
            return

        await _send_due_nudge(
            db, club, mix_, phase, now, deadline, window_hours, settings, push_token_service, report
        )
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
        push_recipients = await gather_push_recipients(db, club.id)
        # Queue the shared-account Spotify playlist generation the moment
        # voting opens (MYS-176/MYS-258) — no admin click needed.
        # enqueue_playlist_job only inserts a row + NOTIFYs; it must land in
        # THIS SAME commit as the state transition above (ADR 0006: "inside
        # the same transaction as the caller's existing work"), not a
        # separate one afterward — a crash between two separate commits would
        # otherwise strand the mix in open_voting with no job ever created and
        # nothing to re-trigger it. The actual generation call runs later, out
        # of this job entirely, in app.jobs.playlist_worker.
        if any(event == "voting_open" for _, event in events):
            await enqueue_playlist_job(db, mix_id, "spotify")
        await db.commit()
        for event_mix, event in events:
            send_mix_event(sender, settings, recipients, club, event_mix, event)
            await send_push_event(
                push_token_service, settings, push_recipients, club, event_mix, event
            )
        report.advanced_to_voting += 1
        return

    # Branch 5: voting deadline passed — close the mix (zero votes still closes).
    events = await advance_mix_state(mix_, club, "closed", db)
    recipients = await gather_recipients(db, club.id)
    push_recipients = await gather_push_recipients(db, club.id)
    # needs_theme (MYS-211) is organizer-only, never the whole club.
    needs_theme_present = any(event == "needs_theme" for _, event in events)
    theme_notice_recipients = await organizer_recipient(db, club) if needs_theme_present else []
    theme_notice_push_recipients = (
        await organizer_push_recipients(db, club) if needs_theme_present else []
    )
    await db.commit()
    for event_mix, event in events:
        is_needs_theme = event == "needs_theme"
        event_recipients = theme_notice_recipients if is_needs_theme else recipients
        event_push_recipients = theme_notice_push_recipients if is_needs_theme else push_recipients
        send_mix_event(sender, settings, event_recipients, club, event_mix, event)
        await send_push_event(
            push_token_service, settings, event_push_recipients, club, event_mix, event
        )
    report.closed += 1


async def advance_due_mixes(
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
    sender: EmailSender | None = None,
    push_token_service: ApplePushTokenService | None = None,
) -> AdvanceReport:
    """Scan live mixes and process each in its own locked transaction.

    Returns an :class:`AdvanceReport`. A single mix's failure is logged and
    counted, never fatal; only a failure of the initial scan propagates."""
    settings = settings or get_settings()
    sender = sender or build_email_sender(settings)
    push_token_service = push_token_service or build_apple_push_token_service(settings)
    now = now or datetime.now(timezone.utc)

    # Read-only scan in its own short-lived session; each mix is then locked and
    # processed in a fresh transaction so one mix's rollback can't touch another.
    async with async_session_factory() as db:
        mix_ids = list(await db.scalars(select(Mix.id).where(Mix.state.in_(_LIVE_STATES))))

    report = AdvanceReport()
    for mix_id in mix_ids:
        try:
            async with async_session_factory() as db:
                await _process_mix(db, mix_id, now, settings, sender, push_token_service, report)
        except Exception:  # noqa: BLE001 — isolate one mix's failure from the rest
            logger.exception("advance_mixes: failed processing mix %s", mix_id)
            report.errors += 1
    return report


async def _run() -> None:
    report = await advance_due_mixes()
    logger.info(
        "advance_mixes: stamped=%d warned=%d pushed_far=%d nudged=%d empty_notices=%d "
        "advanced=%d closed=%d skipped=%d errors=%d",
        report.stamped,
        report.warned,
        report.pushed_far,
        report.nudged,
        report.empty_notices,
        report.advanced_to_voting,
        report.closed,
        report.skipped,
        report.errors,
    )
    print(
        f"advance_mixes: stamped={report.stamped} warned={report.warned} "
        f"pushed_far={report.pushed_far} nudged={report.nudged} "
        f"empty_notices={report.empty_notices} "
        f"advanced={report.advanced_to_voting} closed={report.closed} "
        f"skipped={report.skipped} errors={report.errors}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())
