"""Tests for the playlist-generation worker (MYS-258, ADR 0006, Slice 1).

``_claim_one_job`` alone (a single session, passed straight in) is exercised
against the test suite's default rollback-scoped ``session_factory``
(monkeypatched onto ``app.jobs.playlist_worker``, the same pattern
``test_advance_mixes.py`` uses for ``advance_mixes``).

Everything that runs a full job (``_run_job``/``_drain_queue``) opens more
than one independent session by design (``_generate_for_job`` and
``_mark_job`` each get their own — see the module docstring on why that's
deliberate). That's exactly the shape ADR 0005's shared-connection fixture
isn't built for: every ``Session`` in a test binds to the *same* physical
connection via a SAVEPOINT, and interleaving several independent Session
objects against that one connection across an `await` chain trips up
SQLAlchemy's async/greenlet bridging (``MissingGreenlet``) even without any
genuine concurrency. So those tests, plus the two genuinely-concurrent ones —
``SELECT ... FOR UPDATE SKIP LOCKED`` under real concurrent dequeue attempts,
and the actual ``LISTEN``/``NOTIFY`` round-trip (a raw asyncpg connection is
inherently separate from anything SQLAlchemy manages anyway) — all use
``real_session_factory``/``real_db_session`` instead: genuinely separate
connections, which is also what production actually does (each
``async_session_factory()`` call pulls a real connection from the pool).

Every test here uses ``FakeSpotifyClient`` (imported from
``test_spotify_routes``) — nothing hits the real Spotify API.
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.jobs.playlist_worker import (
    STALE_RUNNING_TIMEOUT_MINUTES,
    _claim_one_job,
    _drain_queue,
    _reclaim_stale_running_jobs,
    _run_job,
    run_worker,
)
from app.models.playlist_job import PlaylistJob
from app.services.playlist_jobs import enqueue_playlist_job
from app.services.spotify_client import SpotifyAuthError
from tests.conftest import TEST_ASYNC_DATABASE_URL
from tests.test_spotify_routes import (
    _SHARED_ACCOUNT_ID,
    FakeSpotifyClient,
    _add_submission,
    _seed_mix,
    _seed_shared_account,
    _seed_user,
)


async def _seed_queued_job(db_session, mix_id: uuid.UUID, provider: str = "spotify") -> None:
    await enqueue_playlist_job(db_session, mix_id, provider)
    await db_session.commit()


@pytest.fixture
def patch_worker_session(monkeypatch, session_factory):
    """Point the worker's ``async_session_factory`` at the test's
    rollback-scoped ``session_factory`` (ADR 0005), same pattern as
    ``test_advance_mixes.py``'s ``run_job`` fixture."""
    monkeypatch.setattr("app.jobs.playlist_worker.async_session_factory", session_factory)


# --------------------------------------------------------------------------- #
# _claim_one_job
# --------------------------------------------------------------------------- #


async def test_claim_one_job_returns_none_when_empty(patch_worker_session, db_session):
    assert await _claim_one_job(db_session) is None


async def test_claim_one_job_marks_running(patch_worker_session, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _seed_queued_job(db_session, mix_.id)

    job = await _claim_one_job(db_session)
    assert job is not None
    assert job.status == "running"
    assert job.started_at is not None


async def test_claim_one_job_skips_unhandled_providers(patch_worker_session, db_session):
    # "apple" is a valid schema value but not dequeued in Slice 1 (see
    # app.models.playlist_job's module docstring) — a stray apple row (there
    # shouldn't be one today, since nothing enqueues one) must never be
    # claimed by this worker.
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _seed_queued_job(db_session, mix_.id, provider="apple")

    assert await _claim_one_job(db_session) is None


async def test_claim_one_job_claims_oldest_first(patch_worker_session, db_session):
    # created_at is set explicitly (rather than via enqueue_playlist_job's
    # server-side now()) because Postgres's now() is fixed for the lifetime of
    # a transaction — and this whole test runs inside one outer transaction
    # (ADR 0005), so two enqueues a moment apart would otherwise tie. Real
    # traffic doesn't hit this: each enqueue call here comes from its own
    # request/job transaction in production.
    organizer = await _seed_user(db_session, "o@example.com")
    mix_a = await _seed_mix(db_session, organizer)
    mix_b = await _seed_mix(db_session, organizer)
    now = datetime.now(timezone.utc)
    # Added out of chronological order, to prove this sorts by created_at
    # rather than insertion/primary-key order.
    db_session.add(
        PlaylistJob(mix_id=mix_b.id, provider="spotify", status="queued", created_at=now)
    )
    db_session.add(
        PlaylistJob(
            mix_id=mix_a.id,
            provider="spotify",
            status="queued",
            created_at=now - timedelta(minutes=5),
        )
    )
    await db_session.commit()

    first = await _claim_one_job(db_session)
    assert first is not None
    assert first.mix_id == mix_a.id


async def test_claim_one_job_concurrent_claims_never_double_claim(
    real_session_factory, real_db_session, monkeypatch
):
    # Genuine SKIP LOCKED contention (ADR 0005): two real connections racing
    # to claim from a two-job queue must walk away with one distinct job
    # each — never the same job twice, never neither claiming anything.
    monkeypatch.setattr("app.jobs.playlist_worker.async_session_factory", real_session_factory)

    organizer = await _seed_user(real_db_session, "o@example.com")
    mix_a = await _seed_mix(real_db_session, organizer)
    mix_b = await _seed_mix(real_db_session, organizer)
    async with real_session_factory() as db:
        await enqueue_playlist_job(db, mix_a.id, "spotify")
        await enqueue_playlist_job(db, mix_b.id, "spotify")
        await db.commit()

    async def _claim() -> uuid.UUID | None:
        async with real_session_factory() as db:
            job = await _claim_one_job(db)
            return job.id if job else None

    claimed = await asyncio.gather(_claim(), _claim())
    assert None not in claimed
    assert len(set(claimed)) == 2  # two distinct jobs, no double-claim

    # The queue is now empty — a third claimer gets nothing.
    async with real_session_factory() as db:
        assert await _claim_one_job(db) is None


# --------------------------------------------------------------------------- #
# _reclaim_stale_running_jobs — review finding: a crashed-mid-job worker must
# not permanently strand a row in `running` (which would also permanently
# block re-enqueue via the partial unique index).
# --------------------------------------------------------------------------- #


async def test_reclaim_resets_stuck_running_job_to_queued(
    real_session_factory, real_db_session, monkeypatch
):
    monkeypatch.setattr("app.jobs.playlist_worker.async_session_factory", real_session_factory)

    organizer = await _seed_user(real_db_session, "o@example.com")
    mix_ = await _seed_mix(real_db_session, organizer)
    stale_start = datetime.now(timezone.utc) - timedelta(minutes=STALE_RUNNING_TIMEOUT_MINUTES + 1)
    stuck = PlaylistJob(
        mix_id=mix_.id, provider="spotify", status="running", started_at=stale_start
    )
    real_db_session.add(stuck)
    await real_db_session.commit()
    stuck_id = stuck.id

    reclaimed = await _reclaim_stale_running_jobs()
    assert reclaimed == 1

    # expire_all(): _reclaim_stale_running_jobs updated this row through a
    # different real connection — real_db_session's identity map still holds
    # the pre-reclaim in-memory copy from the `add()`/`commit()` above, and
    # Session.get() returns that cached object without re-querying unless
    # told the cache is stale.
    real_db_session.expire_all()
    row = await real_db_session.get(PlaylistJob, stuck_id)
    assert row.status == "queued"
    assert row.started_at is None


async def test_reclaim_leaves_fresh_running_job_alone(
    real_session_factory, real_db_session, monkeypatch
):
    # A job that's only just started (well within the timeout) is presumably
    # still being legitimately worked on — must not be touched.
    monkeypatch.setattr("app.jobs.playlist_worker.async_session_factory", real_session_factory)

    organizer = await _seed_user(real_db_session, "o@example.com")
    mix_ = await _seed_mix(real_db_session, organizer)
    fresh_start = datetime.now(timezone.utc) - timedelta(minutes=1)
    fresh = PlaylistJob(
        mix_id=mix_.id, provider="spotify", status="running", started_at=fresh_start
    )
    real_db_session.add(fresh)
    await real_db_session.commit()
    fresh_id = fresh.id

    reclaimed = await _reclaim_stale_running_jobs()
    assert reclaimed == 0

    row = await real_db_session.get(PlaylistJob, fresh_id)
    assert row.status == "running"
    assert row.started_at is not None


async def test_reclaim_leaves_queued_and_terminal_jobs_alone(
    real_session_factory, real_db_session, monkeypatch
):
    monkeypatch.setattr("app.jobs.playlist_worker.async_session_factory", real_session_factory)

    organizer = await _seed_user(real_db_session, "o@example.com")
    mix_a = await _seed_mix(real_db_session, organizer)
    mix_b = await _seed_mix(real_db_session, organizer)
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    real_db_session.add(PlaylistJob(mix_id=mix_a.id, provider="spotify", status="queued"))
    real_db_session.add(
        PlaylistJob(
            mix_id=mix_b.id,
            provider="spotify",
            status="complete",
            started_at=old,
            finished_at=old,
        )
    )
    await real_db_session.commit()

    reclaimed = await _reclaim_stale_running_jobs()
    assert reclaimed == 0


async def test_stuck_running_job_is_reclaimed_and_actually_reprocessed(
    real_session_factory, real_db_session, monkeypatch
):
    """End-to-end proof, not just a status-flip assertion: a job stuck in
    `running` past the timeout — simulating a worker that crashed mid-job —
    is reclaimed back to `queued` and then genuinely re-claimed and completed
    by the ordinary dequeue path, exactly as if it were a fresh job."""
    from app.config import Settings

    monkeypatch.setattr("app.jobs.playlist_worker.async_session_factory", real_session_factory)

    organizer = await _seed_user(real_db_session, "o@example.com")
    mix_ = await _seed_mix(real_db_session, organizer)
    await _seed_shared_account(real_db_session)
    await _add_submission(
        real_db_session,
        mix_.id,
        organizer.id,
        isrc="I-MATCH",
        title="hit",
        spotify_track_uri="spotify:track:pre-resolved",
    )
    stale_start = datetime.now(timezone.utc) - timedelta(minutes=STALE_RUNNING_TIMEOUT_MINUTES + 1)
    # A row exactly as a real crash would leave it: claimed (`running`,
    # `started_at` stamped) but never resolved to complete/failed.
    stuck = PlaylistJob(
        mix_id=mix_.id, provider="spotify", status="running", started_at=stale_start
    )
    real_db_session.add(stuck)
    await real_db_session.commit()
    stuck_id = stuck.id

    # Before reclaim: this row is genuinely stuck — enqueue_playlist_job for
    # the same (mix, provider) is blocked by the partial unique index (it's
    # still an "active" status), and it is NOT claimable.
    async with real_session_factory() as db:
        await enqueue_playlist_job(db, mix_.id, "spotify")
        await db.commit()
    assert (
        len(
            list(
                await real_db_session.scalars(
                    select(PlaylistJob).where(PlaylistJob.mix_id == mix_.id)
                )
            )
        )
        == 1
    ), "a stuck running row must block a fresh enqueue, same as any other active job"
    async with real_session_factory() as db:
        assert await _claim_one_job(db) is None

    reclaimed = await _reclaim_stale_running_jobs()
    assert reclaimed == 1

    # Now it's genuinely re-claimable and re-runnable through the ordinary path.
    async with real_session_factory() as db:
        job = await _claim_one_job(db)
    assert job is not None
    assert job.id == stuck_id

    fake = FakeSpotifyClient()
    settings = Settings(spotify_playlist_account_user_id=str(_SHARED_ACCOUNT_ID))
    await _run_job(job, settings, fake)

    real_db_session.expire_all()  # see the earlier reclaim test for why
    row = await real_db_session.get(PlaylistJob, stuck_id)
    assert row.status == "complete"
    assert fake.created is not None  # generation genuinely ran this time


async def test_run_worker_reclaims_stale_job_each_loop_iteration(
    real_session_factory, real_db_session, monkeypatch
):
    """Confirms the reclaim is actually wired into ``run_worker``'s loop (not
    just callable in isolation) — a stale `running` row left over from a
    previous crash gets reclaimed and completed without any manual
    intervention, purely by the worker starting up and running its ordinary
    loop."""
    from app.config import Settings

    monkeypatch.setattr("app.jobs.playlist_worker.async_session_factory", real_session_factory)

    organizer = await _seed_user(real_db_session, "o@example.com")
    mix_ = await _seed_mix(real_db_session, organizer)
    mix_id = mix_.id
    stale_start = datetime.now(timezone.utc) - timedelta(minutes=STALE_RUNNING_TIMEOUT_MINUTES + 1)
    real_db_session.add(
        PlaylistJob(mix_id=mix_id, provider="spotify", status="running", started_at=stale_start)
    )
    await real_db_session.commit()

    settings = Settings(database_url=TEST_ASYNC_DATABASE_URL)
    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(
        run_worker(settings=settings, client=FakeSpotifyClient(), stop_event=stop_event)
    )
    try:
        deadline = time.monotonic() + 5.0
        row = None
        while time.monotonic() < deadline:
            async with real_session_factory() as db:
                row = await db.scalar(select(PlaylistJob).where(PlaylistJob.mix_id == mix_id))
            if row is not None and row.status in ("complete", "failed"):
                break
            await asyncio.sleep(0.05)
        assert row is not None
        assert row.status == "complete"  # unconfigured shared account -> no-op complete
    finally:
        stop_event.set()
        await asyncio.wait_for(worker_task, timeout=5.0)


# --------------------------------------------------------------------------- #
# _run_job
# --------------------------------------------------------------------------- #


async def test_run_job_unconfigured_completes_as_noop(
    real_session_factory, real_db_session, monkeypatch
):
    # No shared account configured — the worker's job-level equivalent of the
    # old inline call site's silent no-op. Must not touch the fake client.
    from app.config import Settings

    monkeypatch.setattr("app.jobs.playlist_worker.async_session_factory", real_session_factory)

    organizer = await _seed_user(real_db_session, "o@example.com")
    mix_ = await _seed_mix(real_db_session, organizer)
    await _seed_queued_job(real_db_session, mix_.id)
    async with real_session_factory() as db:
        job = await _claim_one_job(db)
    fake = FakeSpotifyClient()

    await _run_job(job, Settings(), fake)

    row = await real_db_session.get(PlaylistJob, job.id)
    assert row.status == "complete"
    assert row.finished_at is not None
    assert fake.created is None  # never called


async def test_run_job_success_generates_and_completes(
    real_session_factory, real_db_session, monkeypatch
):
    from app.config import Settings

    monkeypatch.setattr("app.jobs.playlist_worker.async_session_factory", real_session_factory)

    organizer = await _seed_user(real_db_session, "o@example.com")
    mix_ = await _seed_mix(real_db_session, organizer)
    await _seed_shared_account(real_db_session)
    await _add_submission(
        real_db_session,
        mix_.id,
        organizer.id,
        isrc="I-MATCH",
        title="hit",
        spotify_track_uri="spotify:track:pre-resolved",
    )
    await _seed_queued_job(real_db_session, mix_.id)
    async with real_session_factory() as db:
        job = await _claim_one_job(db)
    fake = FakeSpotifyClient()
    settings = Settings(spotify_playlist_account_user_id=str(_SHARED_ACCOUNT_ID))

    await _run_job(job, settings, fake)

    row = await real_db_session.get(PlaylistJob, job.id)
    assert row.status == "complete"
    assert row.error is None
    assert fake.created is not None
    assert fake.created["public"] is True
    assert fake.added == ["spotify:track:pre-resolved"]


async def test_run_job_spotify_failure_marks_failed_with_error(
    real_session_factory, real_db_session, monkeypatch
):
    from app.config import Settings

    class _RejectingClient(FakeSpotifyClient):
        async def refresh_access_token(self, refresh_token):
            raise SpotifyAuthError("invalid_grant")

    monkeypatch.setattr("app.jobs.playlist_worker.async_session_factory", real_session_factory)

    organizer = await _seed_user(real_db_session, "o@example.com")
    mix_ = await _seed_mix(real_db_session, organizer)
    await _seed_shared_account(real_db_session)
    await _add_submission(real_db_session, mix_.id, organizer.id, isrc="I-MATCH", title="hit")
    await _seed_queued_job(real_db_session, mix_.id)
    async with real_session_factory() as db:
        job = await _claim_one_job(db)
    settings = Settings(spotify_playlist_account_user_id=str(_SHARED_ACCOUNT_ID))

    await _run_job(job, settings, _RejectingClient())

    row = await real_db_session.get(PlaylistJob, job.id)
    assert row.status == "failed"
    assert row.finished_at is not None
    assert "invalid_grant" in row.error


async def test_run_job_missing_mix_marks_failed(patch_worker_session, monkeypatch):
    # A dangling mix_id can't actually be created against the real
    # playlist_jobs table today — its FK to mixes(id) forbids it, and nothing
    # in this app deletes a mix while a playlist_jobs row still references it
    # (the club hard-delete cascade doesn't touch playlist_jobs at all; see
    # the note in this PR about that pre-existing cascade-order gap, which
    # also affects spotify_mix_playlists/apple_mix_playlists and predates this
    # ticket). So this exercises the defensive branch directly with an
    # in-memory job object that was never persisted, rather than fighting a
    # real FK constraint just to reach it.
    from app.config import Settings

    calls: list[tuple[uuid.UUID, str, str | None]] = []

    async def _fake_mark_job(job_id: uuid.UUID, status_: str, error: str | None) -> None:
        calls.append((job_id, status_, error))

    monkeypatch.setattr("app.jobs.playlist_worker._mark_job", _fake_mark_job)

    fake_job = PlaylistJob(
        id=uuid.uuid4(), mix_id=uuid.uuid4(), provider="spotify", status="running"
    )

    await _run_job(fake_job, Settings(), FakeSpotifyClient())

    assert len(calls) == 1
    job_id, status_, error = calls[0]
    assert job_id == fake_job.id
    assert status_ == "failed"
    assert error is not None and "no longer exists" in error


# --------------------------------------------------------------------------- #
# _drain_queue
# --------------------------------------------------------------------------- #


async def test_drain_queue_processes_every_queued_job(
    real_session_factory, real_db_session, monkeypatch
):
    from app.config import Settings

    monkeypatch.setattr("app.jobs.playlist_worker.async_session_factory", real_session_factory)

    organizer = await _seed_user(real_db_session, "o@example.com")
    mix_a = await _seed_mix(real_db_session, organizer)
    mix_b = await _seed_mix(real_db_session, organizer)
    await _seed_queued_job(real_db_session, mix_a.id)
    await _seed_queued_job(real_db_session, mix_b.id)

    processed = await _drain_queue(Settings(), FakeSpotifyClient())
    assert processed == 2

    rows = await real_db_session.scalars(
        select(PlaylistJob).where(PlaylistJob.status == "complete")
    )
    assert len(list(rows)) == 2


# --------------------------------------------------------------------------- #
# LISTEN/NOTIFY round-trip — genuinely against real Postgres (ADR 0006)
# --------------------------------------------------------------------------- #


async def test_worker_processes_job_via_notify_promptly(
    real_session_factory, real_db_session, monkeypatch
):
    """Confirms the LISTEN/NOTIFY round-trip itself, not just the poll
    fallback: a job enqueued *after* the worker starts LISTENing is picked up
    in well under ``POLL_INTERVAL_SECONDS`` (30s) — if this only passed by
    hitting the poll fallback, it would take ~30s, not the sub-second budget
    asserted below.
    """
    from app.config import Settings

    monkeypatch.setattr("app.jobs.playlist_worker.async_session_factory", real_session_factory)

    organizer = await _seed_user(real_db_session, "o@example.com")
    mix_ = await _seed_mix(real_db_session, organizer)
    mix_id = mix_.id

    settings = Settings(database_url=TEST_ASYNC_DATABASE_URL)
    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(
        run_worker(settings=settings, client=FakeSpotifyClient(), stop_event=stop_event)
    )
    try:
        # Let the worker's LISTEN connection attach before enqueuing.
        await asyncio.sleep(0.3)

        started = time.monotonic()
        async with real_session_factory() as db:
            await enqueue_playlist_job(db, mix_id, "spotify")
            await db.commit()

        deadline = started + 5.0
        row = None
        while time.monotonic() < deadline:
            async with real_session_factory() as db:
                row = await db.scalar(select(PlaylistJob).where(PlaylistJob.mix_id == mix_id))
            if row is not None and row.status in ("complete", "failed"):
                break
            await asyncio.sleep(0.05)

        elapsed = time.monotonic() - started
        assert row is not None
        assert row.status == "complete"  # unconfigured shared account -> no-op complete
        assert elapsed < 5.0, "job wasn't picked up promptly — NOTIFY delivery likely broken"
    finally:
        stop_event.set()
        await asyncio.wait_for(worker_task, timeout=5.0)
