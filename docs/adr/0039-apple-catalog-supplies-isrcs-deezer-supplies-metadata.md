# ADR 0039: Apple Music's catalog supplies ISRCs, Deezer supplies everything displayed or stored

**Status:** Accepted, with an open licensing question (see below)
**Date:** 2026-09-29

## Context

`MysteryMixClub-etjx`. Song identity is built on ISRCs, and until now the only
source of one was Deezer's keyless search (technical design section 8). On
2026-09-29 we found that Deezer had silently broken its `artist:"..."` search
filter (HTTP 200, empty list, no error, first seen upstream 2026-09-23), which
took song search and every paste-a-link funnel down with it
(`MysteryMixClub-0ui0`). That was patched with a query workaround, but it
exposed the underlying problem: a single keyless third party with no SLA sits
on the critical path of every submission.

We already hold an Apple Developer Program membership, a MusicKit key and a
working server-side developer token (MYS-105, `apple_music_token.py`).
Measured the same day against 15 real tracks from a production club, Apple's
catalog search called with **only** that developer token (no Music User Token)
returned the right artist and an ISRC for **15 of 15**, versus 14 of 15 for
Deezer's search after the workaround, 9 of 15 for MusicBrainz and 0 of 15 for the
iTunes Search API (which carries no ISRC at all). Median latency was about
250 ms.

Alternatives weighed: MusicBrainz (free, but patchy ISRC coverage, a hard
1 request/second limit, and announced breaking API changes effective
2026-11-30); Spotify search (15 of 15 too, but the app must work without
Spotify, so it can only ever be optional); staying on Deezer alone (no
redundancy). Apple was the strongest single source and needs nothing we do not
already have.

**The licensing question is open and we are building anyway, by explicit
decision.** Apple's Developer Program License Agreement, section 3.3.6(D)
("MusicKit"), may restrict using catalog lookups for purposes unrelated to Apple
Music subscriptions. We could not retrieve that section's text (the agreement
page truncates before it), and pulling only ISRCs does not resolve the
uncertainty. Dawn authorized implementation while Apple's clarification is
pending. **This ADR does not claim the use is legally approved, and it does not
invent a retention or re-fetch deadline**; either would be a guess. If Apple's
answer is no, the remedy is the switch below, not a code change.

## Decision

- **Apple is asked only for candidate ISRCs.** Catalog search
  (`/v1/catalog/{storefront}/search?types=songs`) for a title/artist query, and a
  direct catalog lookup (`/v1/catalog/{storefront}/songs/{id}`) for a pasted Apple
  Music song URL, using that URL's own storefront. Developer token only.
- **Deezer supplies everything displayed or persisted.** Each candidate ISRC is
  resolved through Deezer's exact `/track/isrc:{isrc}` lookup, and the title,
  artist, album, artwork and Deezer track identity all come from that response,
  so the picker and identity response shapes are unchanged. A candidate Deezer
  cannot enrich is **omitted, never shown with Apple's metadata**. A gap is
  acceptable; a track assembled from two sources is not.
- **Never accept the first row on faith.** Candidates are ranked with the shared
  relevance scorer, rows under a minimum relevance are dropped, rows without an
  ISRC are dropped, and duplicate ISRCs (Apple lists a recording once per album,
  single and compilation) are collapsed, then capped. The user still picks from
  the resulting list.
- **Deezer is the fallback for everything.** No Apple credentials, a 429, a
  timeout, a rejected token, an unusable response, no relevant candidates, or no
  candidate Deezer can enrich all fall through to the existing Deezer search.
- **Configurable, no code change to switch back.** `SONG_SEARCH_PROVIDER` is
  `apple` (default) or `deezer`. `apple` with no credentials behaves exactly like
  `deezer`. `SONG_SEARCH_APPLE_STOREFRONT` (default `us`) is used for picker
  searches, which have no user region.
- **Cached in memory for 10 minutes, keyed by query and storefront.** Only a
  successful, enriched result is cached. A failure or an empty outcome is never
  stored, so a transient Apple problem cannot be replayed as "no results".
- **Bounded.** 6 s Apple timeout (search runs in a user's request), at most 10
  candidates enriched per search, and at most 5 Deezer lookups in flight
  **process-wide** (one gate shared by every search, so simultaneous users do not
  multiply the load). A Deezer 429 during enrichment stops the rest of that
  search's lookups. Nothing logs a token, a key, or the user's query.
- Apple playlist creation and Apple link generation (`song_links.py`) are
  untouched.

## Consequences

- **A second vendor on the critical path**, gated on the $99/year membership, the
  MusicKit key and the token being valid in each environment. A lapse degrades to
  Deezer rather than breaking search, which is the point of the fallback.
- **More upstream calls per uncached search:** one Apple search plus up to 10
  Deezer lookups (previously one Deezer search). The process-wide concurrency cap
  and the 10-minute cache limit the burst, but **concurrency is not a rate
  limit**: sustained heavy traffic could still exceed Deezer's 50 requests / 5 s
  per-IP quota. The failure mode is graceful (enrichment 429 -> fall back to
  Deezer search -> if that is also throttled the route returns 429 "try again
  shortly"), and is far above a friend-group app's load. If it ever bites, the
  next step is a real rate limiter and a per-ISRC lookup cache, not a bigger
  gate.
- **The default deviates from `docs/feature-flags.md`'s "default off" rule.** It is
  a provider selector, not a boolean, and it is inert without credentials, but on
  an environment that already holds Apple credentials the first deploy switches
  it on. That was chosen deliberately (per-request fallback bounds the blast
  radius); the alternative was `deezer` by default plus an env change per
  environment, which prod cannot make without the manual secrets route.
- **Apple-derived data is stored indirectly.** The ISRC we persist as a song's
  identity may now have come from Apple. Whether that is permitted is exactly the
  open licensing question above.
- **Storefront is a default, not the user's.** Picker searches use
  `SONG_SEARCH_APPLE_STOREFRONT` because reading a user's storefront needs a
  Music User Token we deliberately never persist (MYS-108, the Apple Music
  integration). A track absent from that storefront's catalog simply falls back
  to Deezer.
- **Known limitation:** a version-specific query can rank a different release
  first (for example asking for "Rebel Rebel - 2016 Remaster" surfaced the "Album
  Version" when Apple's page did not include the remaster). The list is there for
  the user to choose from.
- Dead code: none. `DeezerSearchClient.search` remains the fallback and the
  no-credentials path.

## Revisit if

- **Apple answers the section 3.3.6(D) question.** If the use is not permitted,
  set `SONG_SEARCH_PROVIDER=deezer` everywhere and record the outcome in a new
  ADR superseding this one; if it is permitted with conditions (retention,
  attribution), record them here as they are actually stated.
- Apple starts rate-limiting the developer token (Apple publishes no limit), or
  its catalog endpoints show a sustained reliability problem.
- Deezer's ISRC lookup or search changes again, or Deezer stops being a viable
  enrichment source. Enrichment currently has no second source.
- Uncached search latency becomes a UX problem (the two-hop design is the cost of
  keeping Apple out of the displayed data).
