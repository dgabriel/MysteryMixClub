"""Enqueue side of the Postgres-backed playlist job queue (ADR 0006, MYS-258
Slice 1).

Replaces the inline ``await generate_mix_playlist(...)`` /
``await try_auto_generate_playlist(...)`` calls that used to run playlist
generation synchronously in the request/job path
(``app.api.routes.mixes``, ``app.jobs.advance_mixes``). The dequeue side
(``LISTEN``/``NOTIFY`` + ``SELECT ... FOR UPDATE SKIP LOCKED``) lives in
``app.jobs.playlist_worker``.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# One channel for every provider — cheap at this job's volume (a handful of
# mixes closing per week), so no per-provider fan-out is worth the extra
# complexity (ADR 0006).
NOTIFY_CHANNEL = "playlist_jobs"

PlaylistJobProvider = Literal["spotify", "apple"]


async def enqueue_playlist_job(
    db: AsyncSession, mix_id: uuid.UUID, provider: PlaylistJobProvider
) -> None:
    """Queue a playlist-generation job for ``(mix_id, provider)`` and wake the
    worker, inside the caller's own transaction.

    Does **not** call ``db.commit()`` — the caller owns the transaction
    boundary, same as every other write in the functions this replaces. A
    ``NOTIFY`` issued inside a transaction is only delivered to listeners once
    that transaction commits, so a caller that later rolls back never wakes
    the worker for work that didn't actually happen.

    Collapses to a no-op when a queued/running job already exists for this
    exact ``(mix_id, provider)`` pair — the partial unique index on
    ``playlist_jobs`` (``uq_playlist_jobs_active_mix_provider``) is what makes
    this safe under concurrent callers, not just this ``ON CONFLICT`` clause
    alone. A prior *terminal* (``complete``/``failed``) row for the same pair
    does not block a fresh enqueue — that index only covers non-terminal
    statuses, so a legitimate re-run always gets its own row.
    """
    # `CAST(:name AS uuid)` rather than `:name::uuid` — SQLAlchemy's `text()`
    # bind-param matcher deliberately does not treat `:name` as a parameter
    # when immediately followed by another `:` (so Postgres's own `::` cast
    # operator elsewhere in a raw query isn't misparsed as a second, bogus
    # bind param); the `::` shorthand silently fails to substitute here.
    await db.execute(
        text(
            """
            INSERT INTO playlist_jobs (id, mix_id, provider, status, created_at)
            VALUES (CAST(:id AS uuid), CAST(:mix_id AS uuid), :provider, 'queued', now())
            ON CONFLICT (mix_id, provider) WHERE status IN ('queued', 'running')
            DO NOTHING
            """
        ),
        {"id": str(uuid.uuid4()), "mix_id": str(mix_id), "provider": provider},
    )
    await db.execute(text(f"NOTIFY {NOTIFY_CHANNEL}"))
