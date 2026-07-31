# ADR 0006: Playlist generation moves to a Postgres-backed job queue (no Redis)

**Status:** Accepted
**Date:** 2026-07-26

## Context

`MysteryMixClub-y49x0v` (Linear MYS-258, P1): playlist generation currently
runs synchronously inside the request path. Confirmed by reading the actual
code, not assumed: `backend/app/services/spotify_playlist_generation.py`
(auto-triggered on mix close, called from `PATCH /mixes/{round_id}` in
`backend/app/api/routes/mixes.py` and from the 15-minute deadline job
`backend/app/jobs/advance_mixes.py`) and
`backend/app/services/apple_playlist_generation.py` (per-player, triggered
from `POST /mixes/{round_id}/apple-playlist`) both make sequential,
unbatched outbound calls to music-platform APIs — no `asyncio.gather`, no
rate-limit handling, one submission at a time. With only 2 gunicorn workers
(`MysteryMixClub-s7bv2t`/MYS-259, just shipped), a few concurrent generation
requests can occupy every worker for the duration of a multi-second external
API call chain, starving unrelated requests — worse at round close, when
generation fan-out coincides with a voting spike.

An initial investigation recommended **arq + same-droplet Redis**: arq is
asyncio-native (calls this codebase's existing `async def` service functions
directly, unlike Celery/RQ which are sync-worker-based and would force a
sync/async bridge this app has nowhere else), and same-droplet Redis (not DO
Managed) was recommended over a managed broker on the reasoning that job
state is disposable/reconstructable, not a system of record like Postgres —
a materially different risk profile than the managed-Postgres question
`MysteryMixClub-prr7` already deferred.

Dawn's response: asked directly what's lighter weight than a Redis queue,
and after a Postgres-based alternative was described, confirmed explicitly
— "prefer postgres whenever possible." This isn't just a preference for this
ticket; it's now a standing default (see the `postgres-first-infra` memory)
to reuse Postgres over adding a new backing service whenever Postgres can
reasonably do the job, rather than defaulting to "the standard tool for this
class of problem."

**Does Postgres actually fit here?** Yes, and not as a compromise:

- **Safe concurrent dequeue**: `SELECT ... FOR UPDATE SKIP LOCKED` is a
  well-established pattern (not novel or fragile) — multiple workers, or a
  worker restart mid-poll, never grab the same row twice.
- **Push, not poll**: Postgres's native `LISTEN`/`NOTIFY` gives near-instant
  dispatch — the inserting transaction does `NOTIFY playlist_jobs`, and the
  worker sits in an async `LISTEN` (via `asyncpg`, already a dependency)
  instead of sleeping on a timer. `NOTIFY` isn't guaranteed-delivery across a
  dropped/reconnecting listener, so the worker also polls on a low-frequency
  backstop interval (e.g. 30s) for anything a missed notification would
  otherwise strand — this combination (push + polling safety net) is the
  same shape libraries like `procrastinate` use internally, not something
  ad hoc.
- **Job volume**: a handful of mixes closing per week at MMC's current
  scale. Postgres's poll-fallback latency (seconds, in the rare case a
  `NOTIFY` is missed) is irrelevant at this volume; Redis's near-zero-latency
  push isn't buying anything real here.

## Decision

Playlist generation moves to an async job queue backed entirely by
Postgres — no Redis, no new backing service. Implementation is **hand-rolled
on top of existing dependencies** (SQLAlchemy + `asyncpg`, both already in
`backend/pyproject.toml`), not a third-party queue library (e.g.
`procrastinate`): the scope (one `jobs` table, one dequeue query, one
`LISTEN`/`NOTIFY` wake-up loop, one systemd-managed worker process) is small
and well-understood enough that a new dependency's own migration/config
conventions would add more surface area than it saves, and it keeps this
consistent with the "boring, self-managed" pattern already established for
`advance_mixes`/`purge_accounts` (systemd unit calling this codebase's own
Python directly, no external job-runner framework).

Scope is staged — this ADR covers **Slice 1 only**, and **Spotify only** —
see the Apple Music carve-out below, discovered during implementation, not
anticipated when this ADR was first drafted:

- A `playlist_jobs` table (mix id, provider, status, timestamps, error text).
- `enqueue_playlist_job(...)`: inserts a row, `NOTIFY`s the channel, inside
  the same transaction as the caller's existing work — replaces the inline
  `await generate_mix_playlist(...)` calls in `mixes.py` and
  `advance_mixes.py`.
- One long-running worker process (new systemd unit, mirroring
  `mysterymixclub-advance-mixes-prod.service`'s shape but persistent, not
  timer-triggered): `LISTEN`s on the channel, falls back to polling every
  30s, dequeues via `SKIP LOCKED`, calls the existing generation functions
  **unchanged**.
- Idempotency: the existing lookup-by-`(mix_id, account_id)`-and-replace
  logic inside `generate_mix_playlist` already prevents duplicate playlists
  on a re-run — carried into the job function unchanged. A `UNIQUE(mix_id,
  provider)` constraint on `playlist_jobs` (partial, excluding terminal
  failed/complete states as needed) prevents a double-enqueue from creating
  two queued rows for the same generation in the first place.
- Job status: surfaced through the **existing** `GET
  /mixes/{id}/spotify-playlist` read endpoint (add a status field) rather
  than a new endpoint — the frontend already has a place to poll.

**Apple Music carve-out, discovered during implementation.** This ADR
originally assumed all three call sites (Spotify auto-generate, Apple
per-player generate, the deadline job) would move to
`enqueue_playlist_job(...)` uniformly. `POST /mixes/{id}/apple-playlist`
does **not** — it stays synchronous, unchanged. Reason: Apple's Music User
Token is an explicitly never-persisted, per-request credential (a
deliberate privacy property of that integration, stated in
`apple_playlist_generation.py`'s own docstring) — a job dequeued later by a
separate worker process would need that token to still exist by then, which
means persisting it somewhere, even transiently, directly contradicting why
it's never persisted today. Separately, `playlist_jobs`'s
`UNIQUE(mix_id, provider)` shape has no way to represent Apple's
per-*player* generation anyway (Spotify is one playlist per mix; Apple is
one per player). Queuing Apple Music generation is not part of this
decision and needs its own explicit design (most likely: don't queue it at
all, and instead address its request-path cost some other way, e.g.
tightening its own per-submission fan-out) — tracked as a follow-up, not
solved here.

**Explicitly deferred to a later slice, not part of this decision's initial
scope**: per-provider retry/backoff, the Spotify shared-30s-rolling-window
rate limiter (needs its own design — almost certainly a Postgres-backed
counter/window, consistent with this same ADR's reasoning, not a
reintroduction of Redis for a narrower purpose), dead-letter visibility
beyond a queryable `failed` status, and SSE (plain polling is very likely
sufficient at 5-10 users; not building it speculatively).

## Consequences

- One new process to operate: the worker, systemd-managed like every other
  background job in this repo. No new backing service (Redis) to configure,
  cap memory for, or monitor separately — the existing DO monitor alerts and
  Postgres itself already cover this.
- The worker imports the same `app.services.*`/`app.models.*` graph as the
  API process (same as `advance_mixes.py` already does) — a third copy of
  that import graph's memory footprint on the 2 vCPU/2GB prod droplet,
  smaller than an equivalent Redis-based worker would have been (no separate
  Redis process at all) but not free; watch actual memory after shipping via
  the existing monitor alerts, same as `MysteryMixClub-s7bv2t` recommended.
- `advance_mixes.py`'s call site changes shape from `await
  generate_mix_playlist(...)` to `enqueue_playlist_job(...)` — the deadline
  job itself becomes faster (it no longer blocks on external API calls
  per mix), pushing that latency onto the new worker instead.
- `LISTEN`/`NOTIFY` requires a persistent connection held by the worker —
  this is one more long-lived Postgres connection alongside gunicorn's pool;
  worth confirming against Postgres's `max_connections` headroom during
  implementation, not assumed to be negligible.
- This doesn't preclude ever introducing Redis later for something Postgres
  genuinely can't do well (e.g. the deferred rate-limiter, if it turns out
  to need true shared atomic counters at a volume Postgres can't serve
  cheaply) — but the standing preference is Postgres-first: reaching for a new
  backing service like Redis needs its own explicit argument each time, not a
  default reach just because it's a familiar tool.

## Revisit if

- Job volume grows enough that `LISTEN`/`NOTIFY` dispatch latency or dequeue
  contention becomes a real, measured problem (not a theoretical one) —
  re-profile before reaching for Redis, don't assume this ADR's volume
  assumptions still hold.
- The deferred rate-limiter design (Slice 2) turns out to need true
  cross-process atomic counters at a frequency Postgres serves poorly —
  evaluate fresh at that point, argue for Redis explicitly if so, per the
  Postgres-first default.
