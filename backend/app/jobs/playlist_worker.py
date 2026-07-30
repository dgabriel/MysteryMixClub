"""Playlist-generation worker (MYS-258, ADR 0006, Slice 1).

A long-running process, systemd-managed like every other background job in
this repo, but unlike ``advance_mixes`` (a timer-triggered ``oneshot``) this
one runs continuously (``Type=simple``, ``Restart=on-failure`` — see
``scripts/mysterymixclub-playlist-worker.service``):

* ``LISTEN``s on the ``playlist_jobs`` Postgres channel (via ``asyncpg``,
  already a dependency) for near-instant dispatch the moment
  ``app.services.playlist_jobs.enqueue_playlist_job`` issues a ``NOTIFY``.
* Falls back to polling every ``POLL_INTERVAL_SECONDS`` regardless — ``NOTIFY``
  is not guaranteed delivery across a dropped/reconnecting listener, so this
  is what catches anything a missed notification would otherwise strand. This
  also means a dropped ``LISTEN`` connection degrades gracefully to
  poll-only latency rather than silently stalling the queue; there is
  deliberately no separate reconnect loop for the listener itself (ADR 0006
  keeps this slice's scope small — the poll fallback already covers it).
* Dequeues via ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple worker
  processes (or this same worker racing its own poll against a NOTIFY
  wakeup) never grab the same row twice.
* Calls the existing, **unchanged** generation engine
  (``generate_mix_playlist``) directly, after resolving the shared account the
  same way the old inline call site used to (``playlist_account_user_id`` +
  ``get_shared_connection``, see ``_generate_for_job`` below) — no sync/async
  bridge needed, this codebase is already fully async.

Only ``provider == "spotify"`` jobs are dequeued in Slice 1. ``"apple"`` is a
valid schema value (see ``app.models.playlist_job``'s module docstring) but no
call site enqueues one yet, so none should ever appear in the queue today;
skip is a defensive no-op if one somehow does, not a normal outcome.

**Stale ``running`` reclaim** (review finding on the initial Slice 1 PR): a
worker crash between claiming a job (``status="running"``) and recording its
outcome would otherwise strand that row in ``running`` forever — and that's
not just a visibility gap, since ``uq_playlist_jobs_active_mix_provider``
treats ``running`` as an active status, a stuck row permanently blocks any
future ``enqueue_playlist_job`` call for that ``(mix_id, provider)`` too, with
no automatic recovery. ``_reclaim_stale_running_jobs`` resets any ``running``
row older than ``STALE_RUNNING_TIMEOUT_MINUTES`` back to ``queued`` (in place,
same row — not a new job), so it re-enters the ordinary ``SKIP LOCKED`` dequeue
path on its own. Runs once per main-loop iteration (so effectively on startup,
and again every wake/poll tick) rather than a separate timer, since it's one
cheap ``UPDATE ... WHERE`` that's a no-op the vast majority of the time.

This does mean a *genuinely* slow job (past the timeout, but still actually
running — not crashed) could theoretically get reclaimed and picked up a
second time concurrently. At this job's actual volume and the generous
default timeout, this is accepted as a rare edge case rather than solved with
full distributed-lock semantics (out of scope for Slice 1) — the existing
idempotent lookup-and-replace logic in ``generate_mix_playlist`` plus the
``UNIQUE(mix_id, user_id)`` constraint on ``spotify_mix_playlists`` bound the
damage (no duplicate playlist *row*, though a duplicate outbound Spotify API
call could still happen).

**Postgres connection headroom** (also raised in review): confirmed against
the actual running Postgres, not assumed. ``max_connections`` is the
unmodified default of **100** on all three environments (dev, staging, prod —
none of `docker-compose.yml`/`bootstrap-droplet.sh`/`bootstrap-droplet-prod.sh`
override it). Existing usage: 2 gunicorn API workers × SQLAlchemy's default
pool (5 base + 10 overflow) tops out at 30 in a rare burst, ~10 steady-state;
`advance_mixes`/`purge_accounts` are short-lived timer processes holding ~1
connection at a time. This worker adds one persistent `asyncpg` LISTEN
connection plus its own default-pooled `async_session_factory` usage
(typically 1 active connection, since jobs are drained one at a time) — worst
case aggregate across everything is roughly 76, comfortably under 100; real
steady-state is closer to 11-12. One more long-lived connection is genuine
headroom, not a risk, at today's job volume and worker count.

Run as::

    python -m app.jobs.playlist_worker
"""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from datetime import datetime, timedelta, timezone
from typing import cast

import asyncpg
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import async_session_factory
from app.models.club import Club
from app.models.mix import Mix
from app.models.playlist_job import PlaylistJob
from app.services.playlist_jobs import NOTIFY_CHANNEL
from app.services.spotify_client import (
    SpotifyApiError,
    SpotifyAuthError,
    SpotifyClient,
    get_spotify_client,
)
from app.services.spotify_playlist_generation import (
    generate_mix_playlist,
    get_shared_connection,
    playlist_account_user_id,
)
from app.services.spotify_token_crypto import SpotifyTokenCryptoError

logger = logging.getLogger("app.jobs.playlist_worker")

# Backstop poll interval (ADR 0006): irrelevant-latency safety net at this
# job's actual volume (a handful of mixes closing per week), not a tight loop.
POLL_INTERVAL_SECONDS = 30
# Providers this worker actually dequeues today — see module docstring.
_HANDLED_PROVIDERS = ("spotify",)
# A `running` job older than this is presumed crashed, not just slow — actual
# generation is a handful of sequential HTTP calls (seconds), so 10 minutes is
# generous headroom, not a tight deadline (see module docstring's "stale
# running reclaim" section).
STALE_RUNNING_TIMEOUT_MINUTES = 10
# Truncate a stored exception message so one pathological error can't bloat
# the row indefinitely; plenty for a diagnostic trail (ADR 0006 defers full
# dead-letter visibility, this is just the queryable `error` column).
_MAX_ERROR_LENGTH = 2000


def _asyncpg_dsn(database_url: str) -> str:
    """``settings.database_url`` is a SQLAlchemy-style ``postgresql+asyncpg://``
    URL; bare ``asyncpg.connect()`` (used here for the raw LISTEN connection,
    outside of SQLAlchemy) needs the driver suffix stripped."""
    if database_url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + database_url[len("postgresql+asyncpg://") :]
    return database_url


async def _claim_one_job(db: AsyncSession) -> PlaylistJob | None:
    """Lock and claim the oldest queued job this worker handles, or ``None``
    if there isn't one.

    ``SKIP LOCKED`` is what makes concurrent claimers (another worker
    process, or this worker's poll racing its own NOTIFY-triggered drain)
    never block on, or double-claim, a row another claim already holds.
    """
    job = await db.scalar(
        select(PlaylistJob)
        .where(PlaylistJob.status == "queued", PlaylistJob.provider.in_(_HANDLED_PROVIDERS))
        .order_by(PlaylistJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(job)
    return job


async def _reclaim_stale_running_jobs() -> int:
    """Reset any ``running`` job stuck past ``STALE_RUNNING_TIMEOUT_MINUTES``
    back to ``queued`` (same row, in place) — a worker crash mid-job must not
    leave a row permanently stuck in `running`, since that also permanently
    blocks re-enqueue for its ``(mix_id, provider)`` via the partial unique
    index. Returns the count reclaimed, for logging. A no-op query the vast
    majority of the time."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_RUNNING_TIMEOUT_MINUTES)
    async with async_session_factory() as db:
        result = cast(
            CursorResult,
            await db.execute(
                update(PlaylistJob)
                .where(PlaylistJob.status == "running", PlaylistJob.started_at < cutoff)
                .values(status="queued", started_at=None)
            ),
        )
        await db.commit()
        return result.rowcount or 0


async def _mark_job(job_id: uuid.UUID, job_status: str, error: str | None) -> None:
    """Record a job's terminal outcome, in its own fresh session/transaction —
    deliberately separate from whatever session ran the generation itself, so
    a failure there (aborted transaction) can never prevent recording it."""
    async with async_session_factory() as db:
        await db.execute(
            update(PlaylistJob)
            .where(PlaylistJob.id == job_id)
            .values(status=job_status, finished_at=datetime.now(timezone.utc), error=error)
        )
        await db.commit()


async def _generate_for_job(
    mix_id: uuid.UUID, settings: Settings, client: SpotifyClient
) -> tuple[str, str | None]:
    """Do the actual generation work for one job, in its own session, and
    report the outcome as data rather than writing it — ``_run_job`` always
    calls ``_mark_job`` itself, strictly after this session has closed, so two
    sessions (this one and ``_mark_job``'s) are never open at once."""
    async with async_session_factory() as db:
        mix_ = await db.scalar(select(Mix).where(Mix.id == mix_id))
        club = await db.scalar(select(Club).where(Club.id == mix_.club_id)) if mix_ else None
        if mix_ is None or club is None:
            return "failed", "mix or club no longer exists"

        account_id = playlist_account_user_id(settings)
        if account_id is None:
            # Not configured on this deployment — the same normal "nothing to
            # do" outcome the old inline call site silently no-op'd on, not a
            # failure to surface.
            return "complete", None
        connection = await get_shared_connection(db, account_id)
        if connection is None:
            # Configured, but the shared account hasn't connected — likewise
            # a normal no-op, not a failure.
            return "complete", None

        await generate_mix_playlist(mix_id, mix_, club, account_id, connection, db, client)
        return "complete", None


async def _run_job(job: PlaylistJob, settings: Settings, client: SpotifyClient) -> None:
    """Execute one claimed job. Never raises — a bad job must not crash the
    worker loop; every outcome (including an unreachable mix/club) ends in a
    recorded ``complete``/``failed`` status."""
    job_id, mix_id = job.id, job.mix_id
    try:
        job_status, error = await _generate_for_job(mix_id, settings, client)
        await _mark_job(job_id, job_status, error)
    except (SpotifyTokenCryptoError, SpotifyAuthError, SpotifyApiError) as exc:
        logger.exception("playlist_worker: job %s failed", job_id)
        await _mark_job(job_id, "failed", str(exc)[:_MAX_ERROR_LENGTH])
    except Exception as exc:  # noqa: BLE001 — isolate one job's failure from the rest
        logger.exception("playlist_worker: job %s failed with an unexpected error", job_id)
        await _mark_job(job_id, "failed", str(exc)[:_MAX_ERROR_LENGTH])


async def _drain_queue(settings: Settings, client: SpotifyClient) -> int:
    """Claim and run jobs one at a time until the queue (of handled
    providers) is empty. Returns how many jobs were processed, for logging."""
    processed = 0
    while True:
        async with async_session_factory() as db:
            job = await _claim_one_job(db)
        if job is None:
            return processed
        await _run_job(job, settings, client)
        processed += 1


async def _wait_for_wake_or_stop(
    wake: asyncio.Event, stop_event: asyncio.Event, timeout: float
) -> None:
    """Block until ``wake`` fires (a NOTIFY arrived), ``stop_event`` fires
    (shutdown), or ``timeout`` elapses (the poll-fallback tick) — whichever
    comes first."""
    wake_task = asyncio.ensure_future(wake.wait())
    stop_task = asyncio.ensure_future(stop_event.wait())
    try:
        await asyncio.wait(
            {wake_task, stop_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        for task in (wake_task, stop_task):
            if not task.done():
                task.cancel()


async def run_worker(
    *,
    settings: Settings | None = None,
    client: SpotifyClient | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """The worker's main loop: LISTEN + poll-fallback + drain, until
    ``stop_event`` is set. Left as a public entry point (rather than folded
    into ``_main``) so tests can run it against a real Postgres with their own
    ``stop_event`` — set it after the first drain to exercise exactly one pass."""
    settings = settings or get_settings()
    client = client or get_spotify_client()
    stop_event = stop_event or asyncio.Event()

    wake = asyncio.Event()

    conn = await asyncpg.connect(_asyncpg_dsn(settings.database_url))

    def _on_notify(*_args: object) -> None:
        wake.set()

    await conn.add_listener(NOTIFY_CHANNEL, _on_notify)
    logger.info(
        "playlist_worker: listening on %r (poll fallback every %ss)",
        NOTIFY_CHANNEL,
        POLL_INTERVAL_SECONDS,
    )
    try:
        while not stop_event.is_set():
            wake.clear()
            reclaimed = await _reclaim_stale_running_jobs()
            if reclaimed:
                logger.warning(
                    "playlist_worker: reclaimed %d stale running job(s) (stuck > %dm)",
                    reclaimed,
                    STALE_RUNNING_TIMEOUT_MINUTES,
                )
            processed = await _drain_queue(settings, client)
            if processed:
                logger.info("playlist_worker: processed %d job(s)", processed)
            await _wait_for_wake_or_stop(wake, stop_event, POLL_INTERVAL_SECONDS)
    finally:
        await conn.remove_listener(NOTIFY_CHANNEL, _on_notify)
        await conn.close()


async def _main() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)
    logger.info("playlist_worker: starting")
    await run_worker(stop_event=stop_event)
    logger.info("playlist_worker: stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
