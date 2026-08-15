"""Expire cached YouTube video ids past the API's 30-day retention limit
(MysteryMixClub-7a7x, ADR 0016).

YouTube API Services Developer Policies III.E.4(d): an API Client "may
temporarily store limited amounts of Non-Authorized Data ... but not longer than
30 calendar days", and must "either delete or refresh the stored data".
``submissions.youtube_video_id`` is resolved via ``search.list`` with an API key
and no user credentials, which makes it Non-Authorized Data. There is no
carve-out for bare resource identifiers.

This job is the **delete** arm, and it is deliberately unconditional: anything
past the window is cleared whether or not a refresh is possible. Refresh is
opportunistic (see below) and must never be a precondition for compliance —
otherwise a YouTube outage or a spent quota would silently park us over the
limit.

**Refresh comes free.** Expiry resets the row to *never attempted* — both
``youtube_video_id`` and ``youtube_lookup_attempted_at`` go NULL — which makes
it indistinguishable from a brand-new submission to
``app.services.youtube_backfill.pending_submissions_stmt``. So the next time
anyone opens that mix, the existing enqueue-on-read path (ADR 0015) queues a
backfill job and the worker resolves a fresh id. A mix nobody opens simply stays
cleared and costs no quota. That satisfies both halves of "delete or refresh"
with no machinery of its own.

**``platform_links`` matters as much as the column.** The assembled
``youtube``/``youtubeMusic`` links are exact ``watch?v=<id>`` URLs, so they
embed the very id being expired. Clearing the column alone would relocate the
data, not delete it; both keys are rewritten back to keyless search deep links,
which is exactly what the assembler emits when nothing resolves.

**Source-only tracks are excluded.** A ``youtube:<id>`` ``source_key`` is
extracted from the URL the submitter pasted (``link_resolver``), never from the
API, so it is not API Data and is not subject to this window. Expiring it would
also destroy the track's identity, since ``source_key`` is what a source-only
submission has instead of an ISRC (MYS-201).

**Ships dark.** Gated on ``YOUTUBE_RETENTION_SWEEP_ENABLED``, default off
(MysteryMixClub-l4cv). With the flag unset the timer may fire and this exits
without reading or writing a row, so the units are safe to install everywhere
and each environment opts in when it's ready. Turning it on is an env change
plus a job run — no redeploy. See ``docs/feature-flags.md``.

Invoked by an external scheduler (systemd timer) as a standalone process, the
same shape as ``app.jobs.purge_login_attempts``:

    python -m app.jobs.expire_youtube_ids
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import async_session_factory
from app.models.submission import Submission
from app.services.song_links import youtube_search_deeplinks

# The policy's own number (III.E.4.d). Not a tuning knob — lowering it is safe,
# raising it past 30 is a compliance violation.
RETENTION_DAYS = 30


async def expire_stale_youtube_ids(
    db: AsyncSession, *, now: datetime | None = None, retention_days: int = RETENTION_DAYS
) -> int:
    """Clear every cached video id older than ``retention_days``, returning the count.

    Written as a row-by-row load rather than a bulk UPDATE because each row's
    replacement deep links are derived from its own title/artist.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)

    stale = list(
        await db.scalars(
            select(Submission).where(
                Submission.youtube_video_id.is_not(None),
                Submission.youtube_lookup_attempted_at < cutoff,
                # User-pasted identity, not API Data — see module docstring.
                Submission.source_key.is_(None),
            )
        )
    )
    for submission in stale:
        submission.youtube_video_id = None
        # Back to "never attempted", so the mix re-resolves on its next view.
        submission.youtube_lookup_attempted_at = None
        links = submission.platform_links
        if links:
            # Replace the exact watch URLs, leaving every other platform's link
            # untouched — only YouTube's is derived from the expiring id.
            submission.platform_links = {
                **links,
                **youtube_search_deeplinks(submission.title, submission.artist),
            }

    await db.commit()
    return len(stale)


async def _run() -> None:
    # The flag is checked here, at the entry point, rather than inside
    # expire_stale_youtube_ids: one decision site (docs/feature-flags.md), and
    # the sweep itself stays a pure function that tests can call directly
    # without touching settings.
    if not get_settings().youtube_retention_sweep_enabled:
        print(
            "youtube retention sweep is disabled "
            "(YOUTUBE_RETENTION_SWEEP_ENABLED unset/false) — nothing to do"
        )
        return
    async with async_session_factory() as db:
        count = await expire_stale_youtube_ids(db)
    print(f"expired {count} cached YouTube video id(s) past {RETENTION_DAYS} days")


if __name__ == "__main__":
    asyncio.run(_run())
