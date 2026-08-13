# 15. YouTube backfill moves off the read path, and a miss is remembered

Date: 2026-08-13

## Status

Accepted. Extends ADR 0006 (the Postgres-backed playlist job queue) to a
provider that is not playlist generation.

## Context

`submissions.youtube_video_id` caches the exact YouTube video id used to build a
mix's `watch_videos` link. It is resolved at submit time. Two things leave it
NULL anyway: rows predating MYS-78, and rows whose submit-time resolve failed.

Both playlist read paths covered that gap inline. `GET /mixes/{id}/playlist` and
`GET /mixes/{id}/spotify-playlist` each awaited one YouTube Data API search per
unresolved submission, serially, inside the loop building the response:

```python
video_id = s.youtube_video_id
if not video_id and not s.source_key:
    video_id = await youtube.video_id_for(s.title, s.artist)
    if video_id:
        s.youtube_video_id = video_id
        backfilled = True
```

Measured against the live API with the configured key: **0.74s per call**. At
roughly 10 songs per mix that is ~7 seconds of serial network time on a page
load, and the mix detail page fetches the playlist for both `open_voting` and
`closed` mixes.

The worse half is the last three lines. The id is written back **only on a
hit**. A miss — no match, a timeout, or a quota 403 — leaves the column NULL,
which is indistinguishable from "never tried". So the next read tries again, and
the one after that, forever. What was designed as a one-time lazy backfill is a
permanent per-request tax on exactly the tracks least likely to ever resolve.

The quota arithmetic guarantees misses in bulk rather than making them rare:
`search.list` costs 100 units against a 10,000/day default, so **100 searches
per day**. Any mix viewed after the budget is spent gets a full set of 403s, all
of them uncached, all of them retried on the next view.

This surfaced when `seed_dev.py` (2026-08-13) began creating 204 submissions
with no `youtube_video_id` on any of them, but the defect is not a seed-data
problem — it is the same tax in production on every track YouTube cannot match.

## Decision

**Two changes, and the second is the one that actually matters.**

**1. The read paths do no upstream work.** Both GETs now serve only the ids
already in the database and enqueue a `youtube` job when any submission is still
pending. The partial unique index `uq_playlist_jobs_active_mix_provider` already
collapses concurrent enqueues, so a mix being viewed by five people queues one
job, not five. The worker (`app.jobs.playlist_worker`) resolves them; the next
load picks them up.

**2. Every *answered* attempt is recorded, hit or miss**, on a new nullable
`submissions.youtube_lookup_attempted_at`. The backfill query selects on
`youtube_video_id IS NULL AND youtube_lookup_attempted_at IS NULL AND source_key
IS NULL`, so a recorded miss is never retried. This is what makes (1) safe:
without it, moving the work to a worker would only relocate the infinite retry.

A timestamp rather than a boolean, deliberately — a future
retry-after-N-days policy needs no second migration.

**"Answered" is doing real work in that sentence.** `video_id_for` flattens
every outcome to `None`: a genuine no-match, a quota 403, a timeout, and an
unconfigured key are indistinguishable to its callers. Recording all four as
attempts is wrong, and not theoretically — **the first live run of this backfill
hit a spent quota and wrote off five resolvable tracks** (Pixies' *Debaser*, New
Order's *Ceremony*, Television's *Marquee Moon*, among others) as permanently
unmatched. YouTube had never been asked about any of them.

So `YouTubeResolver.resolve` returns a `YouTubeLookup(video_id, answered)`
alongside the flattened `video_id_for`, and only `answered=True` outcomes are
stamped. A track YouTube refused to answer for stays pending and comes back on
the next job — the queue is the retry mechanism, which is why a quota-blocked
job still reports `complete` rather than `failed`. The submit path takes the
same split, so a submission made during an outage isn't written off either.

Within a job, lookups run concurrently under a semaphore of 4. The ceiling is
politeness to a quota-metered API rather than throughput; it turns a 12-song
backfill from ~9s into ~2s.

## Consequences

**A track YouTube searched for and could not match stays unmatched until someone
intervenes.** This is the deliberate trade and the real cost of this ADR.
Previously such a track got another chance on every page view — at the price of
making every page view slow for everybody. Now one *answered* miss is final.
Clearing `youtube_lookup_attempted_at` for a row is the recovery, and it is a
deliberate operator action, not something the app does on its own.

That is acceptable because the failure mode is visible and bounded: a missing
track shows up as a gap in the YouTube link and in the "N of M on YouTube"
count, and the playlist has always been best-effort with every platform
degrading to a search deep link.

**Environmental failures self-heal, by contrast.** Quota exhaustion, a
misconfigured key, or YouTube being down leave the rows pending, so the next
enqueued job retries them. No operator action needed. The daily quota (100
`search.list` calls against the 10,000-unit default) means a large backlog
drains over several days rather than in one pass, and each mix view re-queues
whatever is still outstanding — slow, but self-correcting and free of user-facing
latency.

**A backfill job that resolves nothing still reports `complete`.** `failed` is
reserved for an actual exception; "the quota was spent" is an expected outcome
with a retry already built in. The worker logs a warning with the pending count
so an outage is visible in the logs rather than silent.

**Reads can no longer repair data.** Both GETs are now genuinely read-only with
respect to submissions, which is the property they should have had. The enqueue
is a write, but to `playlist_jobs`, not to the data being read.

## Alternatives considered

**Parallelize the in-request lookups and stop there.** `asyncio.gather` over the
loop takes ~7s down to ~1s, which reads like a fix. It is not: the retry-forever
behavior survives untouched, every mix view still spends quota, and a read path
still depends on a third-party API's availability to answer at all. It treats
the symptom that is easiest to measure.

**A second, dedicated queue for non-playlist background work.** Cleaner naming —
`playlist_jobs` carrying a job that generates no playlist is a real semantic
stretch, and worth naming as the cost of this decision. Rejected because the
work is the same shape in every way that matters (slow, third-party, per-mix,
must not run in a request) and the existing table already provides the
double-enqueue collapsing, stale-`running` reclaim, and dead-letter column this
would otherwise need rebuilt. One queue with a slightly loose name beats two
queues.

**Drop the lazy backfill entirely and run a one-off script for the NULL rows.**
Simplest possible read path, and tempting since submit-time resolution already
covers new submissions. Rejected because it leaves no path at all for a
submit-time failure: a track whose resolve times out during submission would
stay unlinked until someone remembered to re-run the script. The worker handles
that case continuously and costs little more.

**Resolve at voting-open instead, alongside Spotify generation.** Fits the
existing lifecycle hook and would warm the cache before anyone loads the page.
Rejected as insufficient on its own — it does nothing for the rows already NULL
today, and a mix can gain submissions in states where that hook has already
fired. Worth revisiting as an *addition* once the backlog has drained.
