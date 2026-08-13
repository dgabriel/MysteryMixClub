# 16. Thirty-day retention for cached YouTube ids, refreshed only on access

Date: 2026-08-13

## Status

Accepted. Constrains ADR 0015, which made never-refreshing an explicit property
of the system.

## Context

`submissions.youtube_video_id` caches the exact video id used to build a mix's
`watch_videos` link. It has been stored indefinitely since MYS-78. ADR 0015
(same day as this one) hardened that: `youtube_lookup_attempted_at` exists
precisely to stop the app re-resolving, so "never refresh" went from an accident
to a design decision.

That decision was made without checking the terms. YouTube API Services
Developer Policies, section III.E.4:

> **(d)** API Clients may temporarily store limited amounts of **Non-Authorized
> Data** for as long as is necessary for the purposes of the API Client but
> **not longer than 30 calendar days**.

with the surrounding requirement to "either delete or refresh the stored data"
and keep it "consistent with the current data available through YouTube API
Services". The definitions settle which bucket we're in:

> **Non-Authorized Data:** API Data accessible by an API Client **without User
> Credentials**.

Our ids come from `search.list` with an API key and no user OAuth. That is
Non-Authorized Data, and the policy contains **no carve-out for bare resource
identifiers** as distinct from richer API Data. So indefinite retention is a
violation, and had been one for a long time before ADR 0015 made it deliberate.

This surfaced while preparing the quota-extension audit — which is a compliance
review, making retention close to the centre of what it examines.

## Decision

**Cached ids expire at 30 days. Deletion is unconditional; refresh is
opportunistic.**

A scheduled sweep (`app.jobs.expire_youtube_ids`, systemd timer, daily, the same
shape as the existing `purge_*` jobs) clears every `youtube_video_id` whose
`youtube_lookup_attempted_at` is older than the window.

Three properties make this work:

**1. Expiry resets the row to "never attempted."** Both `youtube_video_id` and
`youtube_lookup_attempted_at` go NULL, which makes an expired row
indistinguishable from a brand-new submission to
`youtube_backfill.pending_submissions_stmt`. The enqueue-on-read path from ADR
0015 then does the refresh for free: open the mix, a backfill job is queued, the
worker resolves a fresh id. **A mix nobody opens simply stays cleared.** Both
halves of "delete or refresh" are satisfied, with no new machinery and no quota
spent on mixes no one plays.

**2. `platform_links` is rewritten, not just the column.** The assembled
`youtube`/`youtubeMusic` entries are exact `watch?v=<id>` URLs and therefore
carry the id being expired. Clearing the column alone would relocate the data
rather than delete it. Both keys go back to keyless search deep links — exactly
what the assembler emits when nothing resolves.

**3. Source-only tracks are excluded.** A `youtube:<id>` `source_key` is
extracted from the URL the submitter pasted, never from the API, so it isn't API
Data. Expiring it would also destroy the track's identity, since `source_key` is
what a source-only submission carries instead of an ISRC (MYS-201).

`RETENTION_DAYS = 30` is the policy's own number, not a tuning knob. Lowering it
is safe; raising it is a violation, and a test pins `<= 30`.

## Consequences

**Old, unplayed mixes lose their YouTube playlist link** until someone opens
them, at which point it comes back a job later. They degrade to search deep
links in the meantime, which is the same fallback the app already uses wherever
a lookup misses. This is the cost of compliance and it is worth paying.

**A steady refresh cost, proportional to what people actually use.** Every
actively-viewed mix re-resolves its tracks every 30 days. Against
`search.list`'s dedicated 100-calls/day bucket that is real but bounded, and it
is why the refresh is access-triggered rather than scheduled: refreshing the
whole catalogue on a timer would cost roughly one call per submission per month
forever, whether or not anyone ever plays it again.

**The sweep is now a compliance control, not an optimisation.** If it stops
running we drift out of policy silently. Hence `Persistent=true` on the timer so
a missed run fires on next boot, and hence deletion that never depends on a
refresh succeeding — a spent quota or a YouTube outage must not be able to park
us past the limit.

## Alternatives considered

**Refresh everything on a 30-day schedule.** The straightforward reading of
"refresh". Rejected on cost: it is one `search.list` call per stored submission
per month, growing with the catalogue and unrelated to use. At 204 submissions
that is already ~7 calls/day of a 100/day budget, spent largely on mixes nobody
will open again.

**Gate deletion on a successful re-resolve.** Keeps every link working. Rejected
outright: it makes compliance contingent on a third party being reachable. ADR
0015 already hit exactly this failure — a spent quota, silently mistaken for a
real answer — and the fix there was to stop conflating "couldn't ask" with an
outcome. Same principle, higher stakes.

**Stop caching entirely and resolve on demand.** Trivially compliant, since
nothing is stored. Rejected: it puts a third-party API back on the read path,
which is the defect ADR 0015 was written to remove, at roughly one call per song
per page view.

**Treat a bare video id as outside the policy.** Tempting — an 11-character
public identifier feels categorically different from user data or content, and
our footprint is a single column with no titles, thumbnails, channels, or
statistics. Rejected because the policy simply doesn't draw that line, and
reading a carve-out into it that isn't written is a bad position to defend
during an audit. The minimal footprint is still worth stating on the form; it
just isn't an exemption.

**Note.** This ADR records a reading of a third party's terms, not legal advice.
Google's audit team is the authority on how they apply III.E.4.
