# Spike — Apple Music integration (links + playlist generation)

**Linear:** MYS-79 · **Status:** findings (research only, no production code)
**Date:** 2026-06-22
**Relates to:** MYS-76 (streaming-playlist spike), MYS-83 (Spotify OAuth playlist), MYS-84 (Deezer go/no-go — NO-GO)

> ⚠️ **Volatility note (same as MYS-76):** Apple Music API terms, endpoints, and
> the MusicKit auth surface change. Every "current state" claim below must be
> re-validated against live Apple developer docs before an implementation ticket
> starts.

---

## 1. Goal

Assess Apple Music as a first-class service for two capabilities:

- **(A) Playback links** — already shipped, keyless. Confirm/where it can improve.
- **(B) Playlist materialization** — generate an Apple Music playlist for a round,
  in line with the broader playlist work (MYS-76).

Verdict up front: **GO, but gated on a paid Apple Developer Program membership
(~$99/yr) and a client-side MusicKit auth step.** Matching is excellent (ISRC).
This is the opposite shape from Deezer (MYS-84): Deezer had great matching but
**no obtainable write access**; Apple has great matching **and** obtainable write
access — the cost is money + a more involved auth model than Spotify's.

---

## 2. What we already have (grounding)

| Asset | Where | Use for this feature |
|-------|-------|----------------------|
| Apple Music **playback link** (keyless) | `app/services/song_links.py` `_apple_exact` → iTunes Search API (`itunes.apple.com/search`), returns `trackViewUrl` | Per-track open-in-Apple links. Read-only; not playlists. |
| **ISRC** per submission | `submissions.isrc` | Canonical key for Apple **catalog** ISRC lookup (better than the title+artist iTunes search we use now). |

**Important:** today's Apple integration is **keyless and read-only** — it uses the
**iTunes Search API** (the old, public, no-auth endpoint), *not* the Apple Music
API. Playlist creation is a different API entirely (`api.music.apple.com`) and a
different, **paid + authenticated** capability class. There is **no MusicKit
integration today.**

### Matching upgrade available regardless of playlists

The current link path searches by `term=title+artist` and takes the first result —
fuzzy. The Apple Music API supports **exact ISRC catalog lookup**:

```
GET https://api.music.apple.com/v1/catalog/{storefront}/songs?filter[isrc]={ISRC}
```

(max 25 ISRCs/call; one ISRC can map to multiple songs → score/pick like the
converters in MYS-76 §8). This needs a **developer token** (see §3), so it only
becomes available once we're in the Apple Developer Program — but it would sharpen
*both* links and playlist matching. Until then, the keyless iTunes Search path stays.

---

## 3. Auth model (the crux)

Apple Music needs **two** tokens, and they live in **different places** — this is
the key difference from our Spotify flow (MYS-83), which is a clean server-side
OAuth code exchange.

### 3.1 Developer token (server-side)

- A **JWT signed with ES256**, using a **MusicKit private key (`.p8`)** created in
  the Apple Developer portal (Certificates, IDs & Profiles → Keys → Media Services).
- Claims: `iss` = Team ID, `kid` = Key ID, `exp` ≤ 180 days, `alg: ES256`.
- **Requires Apple Developer Program membership (~$99/yr).** This is the gate.
- Server-side only (private key is a secret). Identifies *our app* to Apple.
- Used as `Authorization: Bearer <developer_token>` on all calls, including the
  keyless-replacement **catalog** reads (ISRC lookup).

### 3.2 Music User Token / MUT (client-side, then relayed)

- Identifies *the end user* and authorizes library writes (create playlist, add
  tracks). Required for anything under `/v1/me/...`.
- **Must be obtained in the browser via MusicKit JS** `music.authorize()`, which
  opens an Apple sign-in **popup**. Unlike Spotify, there is **no pure server-side
  code→token exchange** — the MUT is minted client-side by MusicKit.
- After `authorize()`, the client holds the MUT; we relay it to our backend so the
  server can perform the writes (`Music-User-Token: <MUT>` header alongside the
  Bearer developer token). MUTs are long-lived but can be revoked/expire → handle
  re-auth.

**Net:** developer token server-side (secret `.p8`), MUT client-side via MusicKit
JS popup then relayed to backend. Architecturally heavier than Spotify, lighter on
external-approval risk (no app-review/quota gate like Spotify dev-mode or Deezer
registration — membership is the only gate, and it's just money).

---

## 4. Playlist materialization (sub-problem B)

Confirmed against current Apple docs — Apple supports the **create-then-add**
shape, the same pattern as our Spotify flow:

1. **Create:** `POST https://api.music.apple.com/v1/me/library/playlists`
   (`LibraryPlaylistCreationRequest`: name, description, and optionally initial
   `tracks`). Returns the new library playlist.
2. **Add tracks:** `POST https://api.music.apple.com/v1/me/library/playlists/{id}/tracks`
   (`LibraryPlaylistTracksRequest`). **Appends to the end only — no reordering**
   via this endpoint. Tracks are added by catalog song id.

Both require **developer token + Music User Token**.

Track ids come from the **ISRC catalog lookup** (§2) — strong, ISRC-exact, the
same quality as Deezer's keyless match. So matching is *not* a risk here.

### Known wrinkles to verify at build time

- **Public link to the result.** Spotify/Deezer return a public, shareable
  playlist URL. Apple **library** playlists live in the user's own library and do
  **not** reliably expose a public `share`/`url` in the API response (historically
  inconsistent). The deliverable for the playlist feature is "a clickable link" —
  we must confirm what URL we can surface (likely `music.apple.com/library/...`,
  which only opens for that signed-in user) before promising a shareable mix link.
  **This is the single biggest open question for the Apple playlist feature.**
- **"Add to Apple-curated playlist not supported"** — only matters for editing
  Apple's own playlists; creating/adding to *our* user-owned playlist is fine.
- **Storefront** — ISRC catalog lookup is per-storefront (`{storefront}` = ISO
  country). Use the user's storefront (available from `/v1/me/storefront` with the
  MUT) so matches resolve in their region.

---

## 5. Keyless / link-only fallback?

**No.** There is no Apple analogue to YouTube's `watch_videos` anonymous playlist
link. Apple playlist creation is **MusicKit/MUT-only**. The keyless tier for Apple
is exactly what we already have: per-track `trackViewUrl` deep links. So Apple
mirrors Spotify (OAuth-only for playlists), not YouTube.

---

## 6. Cost / gating / risk summary

| Factor | Apple Music | vs. our other services |
|--------|-------------|------------------------|
| **Hard cost** | **~$99/yr Apple Developer Program** (required for the developer token) | Spotify free; YouTube free; Deezer free-but-closed |
| **External approval gate** | None beyond membership (no app-review/quota gate found for catalog + library playlist) | Spotify has dev-mode user caps + quota-extension review; Deezer registration **closed** |
| **Auth complexity** | **Higher** — two tokens, MUT is client-side via MusicKit JS popup | Spotify: single server-side OAuth |
| **Matching** | **Excellent** — ISRC catalog filter | Tied with Deezer; better than YouTube |
| **Shareable result link** | ⚠️ **Open question** — library playlists may not expose a public URL | Spotify/Deezer return public URLs |
| **Keyless playlist path** | None | Only YouTube has one |

**Biggest risks:** (1) the **$99/yr** standing cost — a real product/budget call,
not a technical one; (2) whether we can surface a **shareable** link to the created
playlist (vs. a link only the owner can open).

---

## 7. Recommendation — phased, after Spotify

Apple slots in as the next per-user-OAuth service after Spotify, *if* the $99/yr
membership is approved:

1. **Decide the spend.** $99/yr Apple Developer Program is a prerequisite for
   *anything* Apple-API (even the matching upgrade). Product/budget call first.
2. **If yes — Phase A (low cost, high value): ISRC matching upgrade.** Once we hold
   a developer token, swap the keyless iTunes-Search Apple link for the **catalog
   ISRC lookup**. Sharpens existing links; no user auth needed (developer token
   only). Small, contained change to `song_links.py`.
3. **Phase B: MusicKit "Connect Apple Music" + create playlist.** Mirror MYS-83's
   Spotify shape but add the **client-side MusicKit JS** auth step to mint the MUT,
   relay it to the backend, then create-then-add. **Spike/confirm the shareable-link
   question (§4) before committing** — if library playlists can't yield a shareable
   URL, scope this as "playlist in *your* library" (still useful: each player
   generates their own), not "one shared mix link."
4. **Reuse** the round→track-resolution service and the "unmatched tracks" handling
   from the broader playlist work (MYS-76 §9) — ISRC catalog lookup plugs straight in.

A pure deep-link-to-search is **not** a playlist (that's already what
`song_links.py` does per track) — same caveat as the other services.

---

## 8. Proposed tickets (to file after sign-off)

1. **Product/budget decision: approve Apple Developer Program (~$99/yr).** Blocks
   everything below. Also covers obtaining Team ID, a Media Services key (`.p8`),
   and Key ID; store the `.p8` as a server secret (per technical-design §11 env
   pattern — add `APPLE_MUSIC_*` keys to `.env.example`).
2. **Developer-token service (server-side).** ES256 JWT signing from the `.p8`,
   cached with ≤180-day rotation. Foundation for 3 + 4.
3. **Matching upgrade: Apple catalog ISRC lookup in `song_links.py`.** Replace the
   keyless iTunes-Search Apple link with `catalog/{storefront}/songs?filter[isrc]`,
   with graceful fallback to the current deep link. (Phase A — no user auth.)
4. **Spike/confirm shareable-link feasibility for library playlists.** Decides the
   shape of ticket 5. Small, do before building the UI.
5. **MusicKit "Connect Apple Music" + create round playlist (Phase B).** Client-side
   MUT via MusicKit JS, relay to backend, create-then-add via the library-playlist
   endpoints. Mirrors MYS-83.

---

## 9. Bottom line

- **Matching: solved-grade.** ISRC catalog lookup is as good as Deezer's, better
  than YouTube's — but it needs the developer token, so it's gated behind membership.
- **Playlist creation: technically GO.** `create-then-add` library-playlist
  endpoints exist and work with developer token + Music User Token; no closed-door
  like Deezer, no anonymous trick like YouTube.
- **Two real gates, both non-technical:** the **$99/yr** spend, and the **shareable
  link** open question. Neither blocks a decision to proceed; both should be settled
  before the Phase B build.
- **Recommended first step if we proceed:** the **matching upgrade** (developer
  token only) — cheap, immediately improves Apple links, and proves out the
  developer-token plumbing before tackling MusicKit client-side auth.
