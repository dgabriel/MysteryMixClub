> Terminology: this document predates the July 2026 rename — "league" is now "club", "round" is now "mystery mix" (internal: mix).

# Spike — Auto-generate streaming playlists (YouTube, Deezer, Spotify)

**Linear:** MYS-76 · **Status:** findings (research only, no production code)
**Date:** 2026-06-21

> Scope decisions for this spike (from product):
> 1. **Full mix on every service** — every song in a round's playlist should appear
>    on *all three* services, which requires resolving each track across services.
> 2. **Compare all auth models** (per-user OAuth vs. app-owned account vs. link-only)
>    and recommend.
>
> ⚠️ **Volatility note:** Spotify, Deezer, and YouTube API terms, quotas, and
> app-approval gates change often and several have tightened recently. Every
> "current state" claim below must be re-validated against live developer docs
> before any implementation ticket is started. Where access is genuinely at risk
> (Deezer especially), that is called out.

---

## 1. Goal

For a given round, produce a **ready-to-open playlist on each supported service,
surfaced as a clickable link**, containing the full set of round submissions.

Two sub-problems, independent of each other:

- **(A) Track resolution** — map each submission to that service's track/video ID.
- **(B) Playlist materialization** — turn those IDs into a real playlist + a link,
  which is where the auth model bites.

---

## 2. What we already have (grounding)

The matching half of this problem is partly solved by existing code — but **less
than an earlier draft of this doc claimed** (see the correction below).

| Asset | Where | Use for this feature |
|-------|-------|----------------------|
| **ISRC** (required per submission) | `submissions.isrc` (`app/models/submission.py`) | Canonical track key for Deezer + Spotify resolution |
| **`platform_links`** (assembled `{platform: url}`) | `submissions.platform_links`, `app/services/song_links.py` | Keyless link map. **Deezer/Apple are exact track URLs; Spotify/YouTube are only *search* deep-links (no track/video id).** Read-only; not playlists |
| Deezer ISRC lookup (keyless) | `song_links.py` `_deezer_exact` → `GET /track/isrc:{isrc}` | Reuse directly for Deezer track IDs |
| Odesli integration | `app/services/odesli.py` (`OdesliClient.resolve`) | Single-file boundary; cross-platform identity. The way to obtain a real Spotify/YouTube track id is to **re-resolve a real track URL through Odesli** |

> **⚠️ Correction (2026-06-21, found while scoping MYS-78):** an earlier draft
> assumed a stored **`odesli_data`** JSONB holding the full Odesli payload with
> per-platform IDs. **That column no longer exists.** MYS-52 renamed it to
> `platform_links` and changed its meaning to the keyless `{platform: url}` map
> above; the raw Odesli payload is **not** persisted. Consequently **no YouTube
> video ids (and no Spotify track ids) are stored today.** Anywhere this doc says
> "mine `odesli_data`" or "we already hold the destination track id," read it as:
> **re-resolve via `OdesliClient.resolve(<a real track URL>)` at generation time
> and cache the result.** Deezer is the exception — its exact ISRC link is stored
> and keyless. The `odesli_data` mentions in `rounds.py`/`odesli.py` are stale comments.

**Important:** everything today is **read-only**. We build links; we never
authenticate as a user or write to a service. Playlist *creation* is a new
capability class (OAuth / write scopes), and technical-design §10 already lists
"Export / playlist copy features" as out-of-scope/future — this spike is that.

---

## 3. Per-service feasibility

### 3.1 Spotify (Web API)

- **Create playlist:** `POST /v1/users/{user_id}/playlists` then
  `POST /v1/playlists/{id}/tracks` with `spotify:track:` URIs.
- **Auth:** playlists are **always owned by a Spotify user**. Creation requires
  **user OAuth** with `playlist-modify-public` / `playlist-modify-private`.
  There is **no anonymous / link-only playlist creation** and no "pre-filled
  playlist via URL".
- **Track resolution:** `GET /v1/search?q=isrc:{ISRC}&type=track` works with an
  **app token (client-credentials)** — no user auth needed for matching. Strong,
  ISRC-exact.
- **Risk:** new apps start in *development mode* (capped user count until a quota
  extension is granted), and Spotify deprecated several Web API endpoints in late
  2024. Playlist + search endpoints remain, but the approval/quota path must be
  validated.

**Verdict:** real playlist ⇒ **per-user OAuth required**. Matching is easy and keyless-ish (app token).

### 3.2 YouTube (Data API v3)

- **Create playlist (durable):** `playlists.insert` + `playlistItems.insert`,
  OAuth scope `youtube`. **Quota is the constraint:** 10,000 units/day default;
  writes cost ~50 units each and **`search.list` costs 100 units**. Resolving a
  12-song round by text search = ~1,200 units before any inserts.
- **Create playlist (keyless, link-only):** the
  **`watch_videos` trick** —
  `https://www.youtube.com/watch_videos?video_ids=ID1,ID2,...` — produces an
  **anonymous, clickable temporary playlist with no OAuth and zero quota for
  creation.** Caps at ~50 videos; the playlist is ephemeral (not saved to a
  library) but is exactly a "clickable link to the whole mix."
- **Track resolution:** YouTube Data API **does not index ISRC**. Matching is
  **text search (title+artist)** → fuzzy and the weakest link of the three.
  Mitigation: get the YouTube id from an **Odesli resolve** (cached on the
  submission after first use) rather than YouTube text-search (saves quota *and*
  improves accuracy).

**Verdict:** best path is the **keyless `watch_videos` link** (no auth, no quota,
matches the goal literally). Durable saved playlists need OAuth + Google app
verification and burn quota.

### 3.3 Deezer (API)

- **Create playlist:** `POST /user/me/playlists` + `POST /playlist/{id}/tracks`,
  OAuth scope `manage_library`.
- **Track resolution:** `GET /track/isrc:{ISRC}` — **keyless and already used in
  our codebase.** Best matching story of the three.
- **Risk — biggest of all three:** Deezer has progressively restricted/wound down
  its developer platform; obtaining new app credentials / OAuth approval has been
  unreliable for years and may not be available at all. **Confirm we can even
  register an app and complete OAuth before committing to Deezer write support.**

**Verdict:** matching is excellent (keyless ISRC); **playlist creation gated on
whether Deezer API access is still obtainable** — treat as a go/no-go investigation.

> **⛔ MYS-84 outcome (2026-06-22): NO-GO — Deezer playlist creation dropped from scope.**
> The go/no-go ran to completion and failed at the first gate:
> - **Check 1 (register a new app): ❌** Deezer's "My Apps" no longer allows creating
>   new applications, so no Application ID / Secret can be obtained. (Confirmed
>   first-hand on a logged-in account; corroborated by Deezer Community + multiple
>   OSS projects reporting new-app creation disabled since ~early 2024, still off
>   in 2025–2026. New API access is partnership-only via a contact-sales form.)
> - **Checks 2–3 (OAuth `manage_library` token → `POST /user/me/playlists`): ❌ unreachable**
>   without app credentials. The portal's **Simple API** is keyless *and read-only
>   by design* ("Unlimited Access… without identification") — it can never write to
>   a user's library; the documented POST/DELETE playlist actions require an OAuth
>   token we cannot mint.
>
> **What still works:** keyless `GET /track/isrc:{isrc}` (verified 200 / real track
> id) — Deezer stays in scope for **per-track playback links** (`song_links.py`,
> already shipped). Only playlist *creation* is dropped. Revisit only if Deezer
> reopens self-serve app registration.

---

## 4. Track resolution across services (sub-problem A)

We do **not** need a new matching engine — reuse what exists, in priority order
(updated per the §2 correction — IDs are **not** pre-stored, so "reuse" means a
keyless lookup or an Odesli re-resolve at generation time, then cache):

1. **Deezer** → exact, keyless, and already stored: the `platform_links` Deezer
   value is a real track URL (`GET /track/isrc:{isrc}`). No extra work.
2. **Spotify / YouTube** → re-resolve a real track URL through
   `OdesliClient.resolve(...)` to get the platform link/id (the Spotify/YouTube
   values in `platform_links` are only search deep-links). **Cache the resolved id
   on the submission** so it's a one-time cost per song. (This is exactly the
   approach taken for MYS-78's YouTube ids.)
3. **Last-resort fallbacks** if Odesli can't place a track:
   - Spotify → `search?q=isrc:` with an app token (keyless-ish).
   - YouTube → text search (costs Data API quota; fuzziest).

This makes YouTube the only service with a real accuracy risk, and the
`watch_videos` link path lets us sidestep its quota entirely.

---

## 5. Auth model comparison (sub-problem B) + recommendation

| Model | Spotify | YouTube | Deezer | Friction | Notes |
|-------|---------|---------|--------|----------|-------|
| **Link-only (no auth)** | ❌ not possible (only deep-link to search) | ✅ `watch_videos` temp playlist | ❌ not possible | None | Only YouTube gives a true keyless playlist link |
| **Copy-paste (no auth)** | ⚠️ **desktop only** (paste URIs into a playlist) | n/a | ❌ no paste path | Low, desktop | Validated: **no mobile bulk paste** on Spotify; also an undocumented, historically flaky client behavior. Bonus tier, not a foundation |
| **App-owned single account** | ⚠️ possible (one shared account posts public playlists) | ⚠️ possible | ⚠️ possible | None for end users | TOS gray area; one library fills up; shared rate limits; not "the user's" playlist |
| **Per-user OAuth** | ✅ | ✅ (durable) | ✅ (if access exists) | High (connect-account flow + provider app verification) | Playlist lands in the user's own library |

**Mobile reality check (validated):** the keyless tier only reaches mobile on
**YouTube** (`watch_videos`). Spotify copy-paste is **desktop-client only** — no
bulk multi-select/paste exists on Spotify mobile, and even on desktop the behavior
is undocumented and has broken across client updates. For a phone-first friend-group
app, treat copy-paste as a desktop bonus, not the primary Spotify path.

**Recommendation — phased, link-first:**

1. **Phase 1 (quick win, no auth):** YouTube `watch_videos` link for the full
   mix. Ships value immediately, no OAuth, no quota, matches the goal exactly.
2. **Phase 2 (per-user OAuth):** "Connect Spotify" → create a real saved playlist.
   Spotify first because its API access is the most reliable and ISRC matching is
   clean. Gate behind an explicit connect-account action.
3. **Phase 3 (go/no-go):** Deezer — *first* confirm app registration + OAuth is
   still obtainable; if yes, mirror the Spotify flow (matching is already keyless).
4. **Decide separately (product/legal):** whether an **app-owned shared account**
   is acceptable as a no-friction alternative to per-user OAuth for Spotify/Deezer.
   It removes the connect step but raises TOS, library-bloat, and rate-limit
   concerns — needs a deliberate call, not a default.

A pure "deep link to a search" is **not** a playlist and shouldn't be sold as the
Spotify/Deezer fallback — it's already what `song_links.py` does per track.

---

## 6. Where it lives

- **Backend:** a resolver endpoint, given a round, that (a) assembles per-service
  track IDs (keyless Deezer lookup + cached Odesli resolves for Spotify/YouTube)
  and (b) for link-only services returns the URL, or (c) drives the OAuth playlist-create flow.
  OAuth token exchange **must** be server-side (client secrets, refresh tokens).
- **Frontend:** a "Generate playlist" affordance on the round (open_voting and/or
  closed views), with a per-service link/button. The YouTube `watch_videos` URL
  can be assembled either side; OAuth-backed services route through the backend.
- Follows the existing single-file-boundary pattern (`odesli.py`, `song_links.py`):
  keep a stable internal schema so a provider swap is contained.

---

## 7. Cost / quota / risk summary

- **YouTube:** 10k units/day; `search.list` = 100 units is the binding cost on the
  OAuth path. The `watch_videos` link avoids it entirely. Durable playlists also
  require Google OAuth **app verification** (review process).
- **Spotify:** free; watch for dev-mode user caps + the quota-extension review.
- **Deezer:** free *if* access is obtainable — that's the open question.
- **Odesli:** free-tier rate limits are already a flagged pre-launch concern
  (technical-design §8). **Caching each resolve on the submission** (resolve once,
  reuse forever) keeps us well under limits — versus re-resolving on every render.

---

## 8. Lessons from playlist-conversion services (Soundiiz, TuneMyMusic, …)

The category that already solved this — Soundiiz, TuneMyMusic, FreeYourMusic,
SongShift, plus open-source projects like `spotify_to_ytmusic` — converges on the
same four-stage pipeline:

1. **Read source** → normalized track list.
2. **Canonicalize** to a service-independent identity — **ISRC primary**, with
   title / artist / album / **duration** as fallback signals.
3. **Resolve on destination** → search the target and **score candidates** against
   that identity; pick the best.
4. **Write via OAuth** → create the playlist through the destination's authorized
   API, then **reconcile failures** (retry on rate-limit, surface unmatched tracks).

**Lessons we should adopt:**

- **ISRC-first, never ISRC-only.** They match on ISRC *plus* metadata and score
  the result, because ISRC is per-recording (a song can have several), occasionally
  wrong, and **absent from YouTube**. Even the best tool lands ~98%, not 100%.
- **Per-user OAuth is the category's table stake for the destination write.** No
  serious converter relies on copy-paste or anonymous tricks to *create* a playlist.
  This confirms our framing: keyless (`watch_videos`, copy-paste) is a bonus tier;
  OAuth is the real path for Spotify/Deezer.
- **Always ship an "unmatched tracks" escape hatch.** Matching is never perfect;
  show the user what couldn't be placed and let them fix it. Don't promise silent perfection.
- **Operational glue matters:** batching, retries on rate-limit/timeout, de-dup,
  and **order preservation** are where the accuracy actually comes from.

**Where we're *better positioned* than a generic converter:**

- Soundiiz can ingest a **share-link URL or JSON file** as a source (no source-side
  OAuth). **We are the source of truth** — we hold ISRC + a real track URL
  (Deezer/Apple) per submission, so we skip stages 1–2 and start at "resolve on
  destination."
- For destination ids we **re-resolve through Odesli once and cache** (see §2
  correction) rather than re-searching on every transfer — still better than a
  converter that searches blind each time, but it's a cache-on-first-use, not a
  pre-stored id. YouTube stays the fuzzy exception.

### 8.1 Build vs. buy — pricing

Both leaders expose B2B/embed APIs, so integrating one (instead of building OAuth
+ matching for three services) is a real option. Findings:

- **API/B2B pricing is not public for either** — Soundiiz and TuneMyMusic both gate
  developer/B2B access behind "contact sales" / custom quote. No self-serve API tier.
- **Consumer pricing (for reference only — these are per-user subs, not embeddable):**
  Soundiiz Premium ≈ \$3–4.50/mo, Creator ≈ \$6.25/mo (annual) / \$9.50 (monthly).
- A vendor route adds a **per-seat or custom contract cost + an external dependency**
  on a flow that's core to our product, and the sales-gated pricing makes it hard to
  even estimate for an MVP.

**Recommendation: roll our own** (matches product preference). We own the hard
half (ISRC + the Odesli resolver to derive/cache destination ids), the keyless
YouTube path needs no vendor, and per-user OAuth for Spotify is well-trodden.
Revisit buy-vs-build only if Deezer (or breadth across many services) turns into
disproportionate maintenance.

---

## 9. Proposed implementation tickets (to file after sign-off)

1. **Track-resolution service** — round → `{service: [trackIds]}`, via keyless
   Deezer ISRC lookup + **cached Odesli resolves** for Spotify/YouTube (resolve
   once, store the id on the submission). Foundation for all below; MYS-78 builds
   the YouTube slice of this.
2. **YouTube `watch_videos` playlist link** — no auth, Phase 1 quick win.
3. **Frontend: "Generate playlist" on the round** — per-service buttons/links.
4. **Spotify per-user OAuth + create playlist** — connect-account flow, server-side tokens.
5. **Deezer API access go/no-go** — confirm registration/OAuth still works; if yes, create-playlist flow.
6. **Match scoring + "unmatched tracks" handling** — score resolution candidates
   (ISRC + title/artist/duration) and surface anything we couldn't place. Borrowed
   straight from the converters; needed wherever we search rather than reuse an
   Odesli ID (esp. YouTube).
7. **Product/legal decision: app-owned shared account vs per-user OAuth** — for Spotify/Deezer friction.

---

## 10. Bottom line

- **Matching is tractable** — ISRC + a keyless Deezer lookup + a cache-on-first-use
  Odesli resolve cover Spotify and Deezer cleanly; YouTube is the only fuzzy one,
  and we can dodge it. (Note: destination ids are derived/cached, **not** pre-stored
  — see the §2 correction.)
- **Materialization is the real work, and it splits by service:** YouTube ships
  keyless today; Spotify needs OAuth (reliable); Deezer needs OAuth *and* an
  access go/no-go first.
- **Recommended first step:** ship the YouTube `watch_videos` link (Phase 1) — it
  delivers a clickable full-mix link with zero auth/quota and validates the UX —
  then layer Spotify OAuth behind a connect-account flow.
