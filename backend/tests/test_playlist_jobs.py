"""Tests for the Postgres-backed playlist job queue's enqueue side and its
partial unique index (MYS-258, ADR 0006, Slice 1).

``enqueue_playlist_job`` itself is exercised against the test suite's default
rollback-scoped ``db_session`` for the simple cases. The genuine-concurrency
case (two callers racing to enqueue the same (mix, provider) pair) needs two
*real*, separate connections — ADR 0005's default fixtures share one physical
connection per test, so they can't actually contend for the partial unique
index. That test uses ``real_session_factory``/``real_db_session`` instead,
same as the existing ``with_for_update()`` row-locking races elsewhere in this
suite (e.g. ``test_club_member_cap.py``).
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.playlist_job import PlaylistJob
from app.services.playlist_jobs import enqueue_playlist_job
from tests.test_spotify_routes import _seed_mix, _seed_user


async def _jobs_for(db_session, mix_id: uuid.UUID) -> list[PlaylistJob]:
    return list(
        await db_session.scalars(
            select(PlaylistJob).where(PlaylistJob.mix_id == mix_id).order_by(PlaylistJob.created_at)
        )
    )


async def test_enqueue_creates_queued_row(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)

    await enqueue_playlist_job(db_session, mix_.id, "spotify")
    await db_session.commit()

    jobs = await _jobs_for(db_session, mix_.id)
    assert len(jobs) == 1
    assert jobs[0].provider == "spotify"
    assert jobs[0].status == "queued"
    assert jobs[0].finished_at is None
    assert jobs[0].error is None


async def test_enqueue_does_not_commit(db_session, monkeypatch):
    # enqueue_playlist_job must leave the transaction boundary to the caller
    # (ADR 0006: the NOTIFY needs to ride the caller's own commit, and a
    # caller that later rolls back must be able to undo the insert too) —
    # spy on commit() directly rather than asserting on rollback-then-read,
    # since every Session in a test shares one physical connection (ADR
    # 0005) and would see the uncommitted row either way.
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)

    committed = False
    original_commit = db_session.commit

    async def _spy_commit() -> None:
        nonlocal committed
        committed = True
        await original_commit()

    monkeypatch.setattr(db_session, "commit", _spy_commit)

    await enqueue_playlist_job(db_session, mix_.id, "spotify")

    assert committed is False


async def test_enqueue_twice_while_queued_collapses_to_one_row(db_session):
    # The double-enqueue case (ON CONFLICT ... DO NOTHING against the partial
    # unique index): a second enqueue for the same (mix, provider) while the
    # first is still queued must not create a second row.
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)

    await enqueue_playlist_job(db_session, mix_.id, "spotify")
    await enqueue_playlist_job(db_session, mix_.id, "spotify")
    await db_session.commit()

    jobs = await _jobs_for(db_session, mix_.id)
    assert len(jobs) == 1
    assert jobs[0].status == "queued"


async def test_enqueue_after_terminal_status_creates_a_new_row(db_session):
    # A legitimate re-run after a prior job already reached a terminal state
    # must NOT be blocked — the partial index only covers queued/running.
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)

    await enqueue_playlist_job(db_session, mix_.id, "spotify")
    await db_session.commit()
    first = (await _jobs_for(db_session, mix_.id))[0]
    first.status = "complete"
    await db_session.commit()

    await enqueue_playlist_job(db_session, mix_.id, "spotify")
    await db_session.commit()

    jobs = await _jobs_for(db_session, mix_.id)
    assert len(jobs) == 2
    assert jobs[0].status == "complete"
    assert jobs[1].status == "queued"


async def test_enqueue_after_failed_status_creates_a_new_row(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)

    await enqueue_playlist_job(db_session, mix_.id, "spotify")
    await db_session.commit()
    first = (await _jobs_for(db_session, mix_.id))[0]
    first.status = "failed"
    first.error = "boom"
    await db_session.commit()

    await enqueue_playlist_job(db_session, mix_.id, "spotify")
    await db_session.commit()

    jobs = await _jobs_for(db_session, mix_.id)
    assert len(jobs) == 2
    assert jobs[0].status == "failed"
    assert jobs[1].status == "queued"


async def test_enqueue_different_providers_both_get_rows(db_session):
    # provider is part of the uniqueness key — a spotify job and an apple job
    # for the same mix must coexist.
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)

    await enqueue_playlist_job(db_session, mix_.id, "spotify")
    await enqueue_playlist_job(db_session, mix_.id, "apple")
    await db_session.commit()

    jobs = await _jobs_for(db_session, mix_.id)
    assert {j.provider for j in jobs} == {"spotify", "apple"}
    assert all(j.status == "queued" for j in jobs)


async def test_partial_unique_index_rejects_a_direct_duplicate_insert(db_session):
    # Belt-and-suspenders: the index itself (not just enqueue_playlist_job's
    # ON CONFLICT clause) is what actually enforces this — prove a raw second
    # INSERT for an already-queued pair is rejected at the DB layer.
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)

    db_session.add(PlaylistJob(mix_id=mix_.id, provider="spotify", status="queued"))
    await db_session.commit()

    db_session.add(PlaylistJob(mix_id=mix_.id, provider="spotify", status="running"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_partial_unique_index_allows_insert_after_terminal_row(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)

    db_session.add(PlaylistJob(mix_id=mix_.id, provider="spotify", status="complete"))
    await db_session.commit()

    db_session.add(PlaylistJob(mix_id=mix_.id, provider="spotify", status="queued"))
    await db_session.commit()  # must not raise

    jobs = await _jobs_for(db_session, mix_.id)
    assert len(jobs) == 2


async def test_concurrent_double_enqueue_collapses_to_one_row(
    real_session_factory, real_db_session
):
    # Genuine cross-connection race (ADR 0005): two callers enqueue the same
    # (mix, provider) pair at the same time. The default db_session fixture
    # shares one physical connection per test, so it can't actually contend
    # for the partial unique index — this needs real_session_factory's
    # separate real connections, same as the existing with_for_update() races
    # elsewhere in this suite (e.g. test_club_member_cap.py).
    organizer = await _seed_user(real_db_session, "o@example.com")
    mix_ = await _seed_mix(real_db_session, organizer)
    mix_id = mix_.id

    async def _enqueue() -> None:
        async with real_session_factory() as db:
            await enqueue_playlist_job(db, mix_id, "spotify")
            await db.commit()

    await asyncio.gather(_enqueue(), _enqueue())

    jobs = await _jobs_for(real_db_session, mix_id)
    assert len(jobs) == 1
    assert jobs[0].status == "queued"
