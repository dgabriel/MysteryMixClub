"""YouTube video-id backfill for a mix's submissions (MysteryMixClub-6jzl, ADR 0015).

``submissions.youtube_video_id`` is normally resolved at submit time
(``app.api.routes.submissions``). This module covers the two cases that leaves
behind: rows that predate MYS-78, and rows whose submit-time resolve failed
(a timeout, or a YouTube quota 403).

Both playlist read paths used to handle that inline — awaiting one
``video_id_for`` call per unresolved submission, serially, inside the loop that
built the response. That cost ~0.74s per song against the live API, and because
a miss was never recorded it repeated on *every* read forever. Now the reads
only enqueue (``app.services.playlist_jobs.enqueue_playlist_job``) and this runs
in the worker.

Two properties matter here:

* **Every answered attempt is recorded**, hit or miss, via
  ``youtube_lookup_attempted_at``. A miss is a real outcome ("YouTube has no
  match for this track"), not a reason to ask again on the next read. An
  *unanswered* attempt — quota 403, timeout, unconfigured key — is not
  recorded at all, so an outage never writes off tracks that were merely
  unreachable at the time.
* **Lookups run concurrently**, bounded by ``_MAX_CONCURRENCY``. Serially, a
  12-song mix took ~9s; the bound keeps that near one round trip without
  opening 12 simultaneous connections to a quota-metered API.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.submission import Submission
from app.services.youtube_resolver import YouTubeLookup, YouTubeResolver

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillResult:
    """One backfill pass. ``unreachable`` is the count YouTube refused to answer
    for; those rows are deliberately left pending rather than written off."""

    hits: int
    misses: int
    unreachable: int


# YouTube's search.list costs 100 quota units per call against a 10,000/day
# default, so the ceiling here is politeness to a metered API, not throughput.
# Four in flight turns a 12-song mix from ~9s into ~2s.
_MAX_CONCURRENCY = 4


def pending_submissions_stmt(mix_id: uuid.UUID):
    """Submissions in ``mix_id`` still eligible for a YouTube resolve.

    Excludes, in order: rows already resolved, rows already attempted (a
    recorded miss is final — ADR 0015), and source-only rows. A ``youtube:``
    source_key already carries its exact id from submit time, and a
    ``bandcamp:`` one must never be linked to a *guessed* video (MYS-201), so
    neither is ever fuzzy-matched.
    """
    return select(Submission).where(
        Submission.mix_id == mix_id,
        Submission.youtube_video_id.is_(None),
        Submission.youtube_lookup_attempted_at.is_(None),
        Submission.source_key.is_(None),
    )


async def has_pending(db: AsyncSession, mix_id: uuid.UUID) -> bool:
    """Whether ``mix_id`` has any submission worth running a backfill for.

    Cheap enough to call on a read path — it's an indexed existence check
    (``ix_submissions_youtube_backfill_pending``), no upstream traffic — which
    is what lets the playlist GETs enqueue only when there's actually work.
    """
    return (
        await db.scalar(pending_submissions_stmt(mix_id).with_only_columns(Submission.id).limit(1))
    ) is not None


async def backfill_mix(
    db: AsyncSession, mix_id: uuid.UUID, youtube: YouTubeResolver
) -> BackfillResult:
    """Resolve every pending submission in ``mix_id``.

    Commits once at the end. ``resolve`` is best-effort by contract and never
    raises, so a single bad track can't strand the rest of the batch.

    Only a submission YouTube actually *answered* for is stamped as attempted.
    A track skipped because the API refused to answer (quota, timeout) stays
    pending and is retried by the next job — otherwise one exhausted-quota run
    would permanently write off every track it touched, which is precisely what
    happened the first time this ran for real.
    """
    submissions = list(await db.scalars(pending_submissions_stmt(mix_id)))
    if not submissions:
        return BackfillResult(0, 0, 0)

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def resolve(s: Submission) -> tuple[Submission, YouTubeLookup]:
        async with semaphore:
            return (s, await youtube.resolve(s.title, s.artist))

    results = await asyncio.gather(*(resolve(s) for s in submissions))

    attempted_at = datetime.now(timezone.utc)
    hits = misses = unreachable = 0
    for submission, lookup in results:
        if not lookup.answered:
            unreachable += 1
            continue  # left pending on purpose — try again next time
        submission.youtube_lookup_attempted_at = attempted_at
        if lookup.video_id:
            submission.youtube_video_id = lookup.video_id
            hits += 1
        else:
            misses += 1

    await db.commit()
    if unreachable:
        logger.warning(
            "youtube backfill for mix %s: %d track(s) left pending — YouTube did not "
            "answer (quota or transport). They stay eligible for the next job.",
            mix_id,
            unreachable,
        )
    logger.info(
        "youtube backfill for mix %s: %d resolved, %d unmatched, %d unreachable",
        mix_id,
        hits,
        misses,
        unreachable,
    )
    return BackfillResult(hits, misses, unreachable)
