# MysteryMixClub — Technical Design

**Document type:** Technical Design  
**Status:** Draft v1.0  
**Phase:** PDLC — Technical Definition  
**Depends on:** `discovery/problem-statement.md`, `discovery/personas.md`, `prd/prd.md`

---

## 1. Overview

MysteryMixClub is a Progressive Web App (PWA) built as a monorepo with a React/TypeScript frontend and a Python/FastAPI backend, backed by PostgreSQL and hosted on DigitalOcean. Security and privacy are first-class architectural concerns, not afterthoughts.

---

## 2. Repository Structure

```
mysterymixclub/
  docs/
    discovery/
      problem-statement.md
      personas.md
      competitive-analysis.md
    prd/
      prd.md
    technical/
      technical-design.md
  frontend/
    public/
      manifest.json
      service-worker.js
    src/
      components/
      pages/
      hooks/
      services/
      types/
  backend/
    app/
      api/
        routes/
      models/
      services/
      auth/
    tests/
  .env.example
  .gitignore
  README.md
```

---

## 3. Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Frontend | React + TypeScript | Component model fits the league/round/submission UI; TypeScript enforces data contracts |
| Styling | Tailwind CSS | Fast to build with, consistent on mobile, no runtime overhead |
| PWA | Web App Manifest + Service Worker | Home screen install, offline shell, native-feel on mobile without App Store |
| Backend | Python / FastAPI | Async-first, fast, Pydantic validation built in, proven in previous iteration |
| Database | PostgreSQL | Relational model fits the data; row-level security enforced at DB layer |
| Auth | Magic link + JWT + refresh tokens | No passwords, low friction, secure two-token session model |
| Email | Resend | Magic links and round notifications; generous free tier; developer-friendly |
| Song identity | Odesli / Songlink API | Cross-platform search and link resolution; ISRC canonical track identity |
| Hosting | DigitalOcean App Platform | Simple, affordable, managed Postgres, no AWS complexity for v1 |

---

## 4. Progressive Web App

MysteryMixClub is a PWA from day one. This is not a post-launch enhancement.

**Requirements at launch:**
- `manifest.json` with app name, icons, theme color, and `display: standalone`
- Service worker for offline shell (app loads even without network; data requires connection)
- HTTPS enforced — required for PWA install prompt and service worker registration
- Mobile-responsive layout, touch-friendly tap targets throughout
- "Add to Home Screen" instructions included in onboarding flow for both iOS and Android

**Why PWA over native app:**
- No App Store review process
- Single codebase for all platforms
- Distribution via email link — users open in browser, optionally install
- Fits the invite-only, friend-group scale of v1

---

## 5. Authentication

### Magic Link Flow

1. User enters email address
2. Server generates a cryptographically random one-time token (minimum 32 bytes, URL-safe)
3. Token is stored in the database with a 15-minute expiry and marked as unused
4. Magic link is emailed via Resend: `https://mysterymixclub.com/auth/verify?token=<token>`
5. User clicks link; server validates token (exists, unexpired, unused)
6. Token is immediately invalidated (single-use, hard delete)
7. Server issues an access token (JWT, 60-minute expiry) and a refresh token (cryptographically random, 30-day expiry)
8. Refresh token is stored server-side in the `sessions` table
9. Access token is stored in memory on the client (never localStorage)
10. Refresh token is stored in an HttpOnly, Secure, **SameSite=Lax** cookie.
    (Originally specced as SameSite=Strict; changed to Lax in MYS-91 so the
    session survives a return from an external OAuth provider — Strict withholds
    the cookie on the cross-site-initiated navigation back and silently logs the
    user out. Lax is safe here because every sensitive endpoint under the cookie
    path is POST, and Lax still withholds the cookie on all cross-site POST/XHR,
    so it can't be CSRF-forged.)

### Token Refresh Flow

- When an access token expires, the client sends the refresh token cookie to `/auth/refresh`
- Server validates the refresh token against the `sessions` table
- If valid: issue a new access token, return to client
- If invalid or expired: return 401, redirect to magic link request
- The user experiences none of this — it is fully silent

### Session Management

- Each login creates a new row in the `sessions` table
- Sessions store: user ID, refresh token hash, device hint (user agent), created at, last used at, invalidated at
- "Log out of all devices" sets `invalidated_at` on all active sessions for that user
- All subsequent refresh attempts against invalidated sessions return 401

### Security Rules

- Magic link tokens: single-use, 15-minute expiry, cryptographically random, hard-deleted on use
- Access tokens: JWT, 60-minute expiry, signed with server secret, never stored in localStorage or cookies
- Refresh tokens: 30-day expiry, stored as a hash in the database, HttpOnly Secure cookie on client
- Rate limiting on `/auth/request` — maximum 5 magic link requests per email per hour
- All endpoints require authentication except `/auth/request` and `/auth/verify`
- HTTPS enforced at the infrastructure level

---

## 6. Data Model

### users
```
id                  UUID PRIMARY KEY
email               TEXT UNIQUE NOT NULL
display_name        TEXT NOT NULL
preferred_service   TEXT (spotify | youtube | deezer)
created_at          TIMESTAMP
deleted_at          TIMESTAMP (soft delete for cascade handling, hard purge on schedule)
```
> *Participation mode is **per-league**, not per-user (MYS-112). The original
> `default_vibe_mode` column on `users` is dropped; the default lives on
> `leagues.default_vibe_mode` and the per-member setting on
> `league_members.vibe_mode`.*

### sessions
```
id                  UUID PRIMARY KEY
user_id             UUID REFERENCES users(id)
refresh_token_hash  TEXT NOT NULL
device_hint         TEXT
created_at          TIMESTAMP
last_used_at        TIMESTAMP
invalidated_at      TIMESTAMP
```

### leagues
```
id                  UUID PRIMARY KEY
name                TEXT NOT NULL
description         TEXT
organizer_id        UUID REFERENCES users(id)
total_rounds        INTEGER NOT NULL
current_round       INTEGER DEFAULT 0
state               TEXT (active | complete)
default_vibe_mode   BOOLEAN DEFAULT FALSE (admin-set default participation mode; seeds league_members.vibe_mode at join — MYS-112)
created_at          TIMESTAMP
completed_at        TIMESTAMP
```

### league_members
```
id                  UUID PRIMARY KEY
league_id           UUID REFERENCES leagues(id)
user_id             UUID REFERENCES users(id)
vibe_mode           BOOLEAN DEFAULT FALSE (per-league participation default; seeded from leagues.default_vibe_mode at join, toggleable anytime — MYS-112)
role                TEXT (admin | member) DEFAULT 'member', CHECK (role IN ('admin', 'member')) — co-organizer support (MYS-99). An "admin" member has full operational parity with the league's fixed organizer_id everywhere organizer checks apply (see §7 annotations below), except they can't be demoted via the role endpoint by anyone but another admin, and the fixed organizer's own row is never touched by it.
joined_at           TIMESTAMP
removed_at          TIMESTAMP
```

### invites
```
id                  UUID PRIMARY KEY
league_id           UUID REFERENCES leagues(id)
created_by          UUID REFERENCES users(id)
token               TEXT UNIQUE NOT NULL
expires_at          TIMESTAMP
created_at          TIMESTAMP
```

### rounds
```
id                  UUID PRIMARY KEY
league_id           UUID REFERENCES leagues(id)
round_number        INTEGER NOT NULL
theme               TEXT (nullable — unset until the organizer names the round)
description         TEXT
state               TEXT (pending | open_submission | open_voting | closed)
submission_deadline TIMESTAMP
voting_deadline     TIMESTAMP
votes_per_player    INTEGER DEFAULT 3
created_at          TIMESTAMP
closed_at           TIMESTAMP
```

The full slate of rounds is auto-generated in the `pending` state when a league
is created, one per `total_rounds` (default 6), numbered 1..N with no theme yet.
Editing a league's `total_rounds` reconciles the slate: raising it appends new
`pending` rounds; lowering it deletes the trailing rounds, which must all still
be `pending` (a started round cannot be removed). The lifecycle is forward-only:
`pending → open_submission → open_voting → closed`. Only one round per league may
be active (`open_submission`/`open_voting`) at a time, enforced when a round
opens. `theme` (nullable) and `description` are editable only while a round is
`pending`; deadlines remain editable until the round closes. Closing a non-final
round auto-opens the next `pending` round; closing the final round completes the
league.

### submissions
```
id                  UUID PRIMARY KEY
round_id            UUID REFERENCES rounds(id)
user_id             UUID REFERENCES users(id)
isrc                TEXT (nullable since MYS-201 — see source_key)
source_key          TEXT (nullable; source-only identity: youtube:<video id> | bandcamp:<artist>/<track> — MYS-201)
title               TEXT NOT NULL
artist              TEXT NOT NULL
album               TEXT
album_art_url       TEXT
odesli_data         JSONB (full Odesli response, for platform resolution at playback)
note                TEXT (max 280 chars)
participation_mode  TEXT (playing | vibing) — per-round mode; defaults at submit from league_members.vibe_mode, overridable per round (MYS-112)
created_at          TIMESTAMP
CHECK (isrc IS NOT NULL OR source_key IS NOT NULL) — ck_submissions_isrc_or_source
```
> *A submission is identified by **exactly one** of `isrc` or `source_key`
> (MYS-201). Catalog tracks carry an ISRC as before; **source-only** tracks —
> ones that exist only on Bandcamp or YouTube, with no ISRC on the indexed
> catalogs — carry a `source_key` instead. The DB CHECK guarantees at least one
> is present; the submit endpoint's validator enforces exactly one. A source_key
> is an **exact** reference (the video id / Bandcamp track page the submitter
> chose) and is **never fuzzy-matched** — a gap (a platform with no link) is
> acceptable, a wrong song is not. Duplicate detection matches on whichever
> identity the submission carries.*

### votes
```
id                  UUID PRIMARY KEY
round_id            UUID REFERENCES rounds(id)
voter_id            UUID REFERENCES users(id)
submission_id       UUID REFERENCES submissions(id)
created_at          TIMESTAMP
UNIQUE(voter_id, submission_id)
```
> *Voting is anonymous throughout `open_voting` — `voter_id` is never surfaced
> to other players before a round closes. Once `rounds.state == "closed"`,
> `GET /rounds/:id/results` reveals each submission's voters by name
> (MYS-173). This does not change vote casting or the anonymous voting
> playlist (§7 Rounds) — it only adds identity to the post-close reveal.*

### notes
```
id                  UUID PRIMARY KEY
round_id            UUID REFERENCES rounds(id)
author_id           UUID REFERENCES users(id)
submission_id       UUID REFERENCES submissions(id)
body                TEXT NOT NULL (max 280 chars)
created_at          TIMESTAMP
```

### magic_link_tokens
```
id                  UUID PRIMARY KEY
email               TEXT NOT NULL
token_hash          TEXT NOT NULL
expires_at          TIMESTAMP NOT NULL
used                BOOLEAN DEFAULT FALSE
created_at          TIMESTAMP
```

---

## 7. API Design

All endpoints are prefixed `/api/v1/`. All responses are JSON. All authenticated endpoints require a valid JWT access token in the `Authorization: Bearer` header.

### Auth
```
POST   /auth/request          Request a magic link (email in body)
GET    /auth/verify           Validate magic link token, issue session
POST   /auth/refresh          Exchange refresh token for new access token
POST   /auth/logout           Invalidate current session
POST   /auth/logout-all       Invalidate all sessions for current user
```

### Users
```
GET    /users/me              Get current user profile
PATCH  /users/me              Update display name, preferred service
DELETE /users/me              Delete account and all associated data (right to be forgotten)
```

### Leagues
```
POST   /leagues               Create a new league (organizer sets default_vibe_mode — MYS-112)
GET    /leagues               Get all leagues for current user
GET    /leagues/:id           Get league detail
PATCH  /leagues/:id           Update league (organizer only: name, total_rounds, default_vibe_mode — co-organizers now have parity, MYS-99)
GET    /leagues/:id/members   Get league members
PATCH  /leagues/:id/membership Set the caller's own vibe_mode for the league (MYS-112)
DELETE /leagues/:id/members/:userId   Remove a member (organizer only — co-organizers now have parity, MYS-99)
PATCH  /leagues/:id/members/:userId/role  Promote/demote an active member to/from co-organizer (organizer or co-organizer only; MYS-99)
```

### Invites
```
POST   /leagues/:id/invites   Generate invite link (organizer or member)
GET    /invites/:token        Validate invite token, return league preview
POST   /invites/:token/accept Join league via invite
```

### Rounds
```
POST   /leagues/:id/rounds        Create a new round (organizer only — co-organizers now have parity, MYS-99)
GET    /leagues/:id/rounds        Get all rounds for a league
GET    /rounds/:id            Get round detail
PATCH  /rounds/:id            Update round (organizer only: theme, deadlines, state — co-organizers now have parity, MYS-99)
GET    /rounds/:id/playlist   Get round playlist with Odesli universal links
GET    /rounds/:id/results    Get round results (scores, Most Noted, vote breakdown, per-song voter identity once closed — MYS-173)
```

### Submissions
```
POST   /rounds/:id/submissions      Submit a song
GET    /rounds/:id/submissions/mine Get current user's submission for a round
GET    /rounds/:id/submissions      Get all submissions (available after voting closes)
```

### Song Search & Resolution
```
GET    /songs/search?q=        Search via Odesli API
POST   /songs/resolve          Resolve a pasted link to canonical track
```

### Votes & Notes
```
POST   /rounds/:id/votes        Cast votes (Playing players only)
GET    /rounds/:id/votes/mine   Get current user's votes
POST   /submissions/:id/notes   Leave a note on a submission
GET    /submissions/:id/notes   Get notes on a submission
```

---

## 8. Odesli Integration

Odesli (Songlink) is the core dependency for platform-agnostic song identity.

### Search
```
GET https://api.song.link/v1-alpha.1/links?url=<encoded_search_url>
```
- Used for native in-app search
- Returns canonical track data including ISRC when available
- Full Odesli response stored as JSONB in `submissions.odesli_data`

### Link Resolution
```
GET https://api.song.link/v1-alpha.1/links?url=<encoded_platform_url>
```
- Used when player pastes a link from any streaming service
- Resolves to canonical track regardless of source platform
- Same JSONB storage pattern as search

### Playback Resolution
- At playlist generation time, Odesli data is used to surface platform-specific URLs
- Player's `preferred_service` determines which URL is surfaced by default
- All available platform links are returned so the player can switch
- YouTube link always included as universal fallback

### Rate Limits & Resilience
- Odesli free tier rate limits must be validated against expected usage before launch
- Failed Odesli lookups must surface a clear error to the user, not a silent failure
- Consider caching resolved track data in the database to reduce repeat API calls

### Source-only resolution (MYS-201)
The keyless resolver funnels YouTube/Bandcamp links through a Deezer search to
recover a canonical ISRC. When that search returns **no** catalog match (a
genuine miss — upstream errors still raise), the link is treated as a
**source-only** track: `POST /songs/resolve` with `allow_source_only: true`
returns the song with a `source`/`source_key`/`source_url` and no ISRC, and its
cross-service links are assembled **without any fuzzy lookup** (the exact
YouTube video id or Bandcamp track page only — every other platform degrades to
a search deep link). `allow_source_only` defaults to `false`, so existing
clients are unaffected: a source-only link still resolves to a 404 exactly as
before. The submitted `source_key` is stored on `submissions.source_key` (see
§6) and is the track's identity for duplicate detection and playlist building.

The read surfaces carry that identity through so clients can badge source-only
tracks and explain playlist gaps (MYS-201):

- The voting-playlist entry (`GET /mixes/{id}/playlist`) and the results/reveal
  track shapes (`GET /mixes/{id}/results`) expose `isrc` (null for source-only)
  plus `source` (`"youtube"`/`"bandcamp"`) and `source_url` — null on a normal
  catalog track — so a source-only pick renders a "YouTube only"/"Bandcamp only"
  badge with a working link.
- The Apple generation response (`POST /mixes/{id}/apple-playlist`) reports each
  skipped track in `unmatched` with `title`, `artist`, a `reason` of
  `"source_only"` (no ISRC — a Bandcamp/YouTube track that can never match a
  catalog) or `"no_catalog_match"` (an ISRC-backed track this storefront doesn't
  carry), plus `source` (`"youtube"`/`"bandcamp"`) and `source_url` — populated
  for a `"source_only"` entry so the frontend can link it out to its page, null
  for a `"no_catalog_match"` entry (it has an ISRC, not a source_key). So the gap
  summary can say *why* rather than only *how many*.
- The shared Spotify playlist is auto-generated on voting-open (no HTTP
  generation call), so its read route `GET /mixes/{id}/spotify-playlist` carries
  the same gap summary: alongside `playlist_url` it returns `unmatched` (a list
  of `{submission_id, title, artist, reason, source, source_url}` with the
  identical `reason`/`source`/`source_url` semantics). The list is recomputed at
  read time from persisted state — generation caches each matched track's
  `spotify_track_uri` on its submission, so a submission with no cached URI is
  exactly one the playlist skipped — and is empty when no playlist exists yet
  (nothing generated, or nothing matched).

---

## 9. Security Checklist

These are non-negotiable requirements, not suggestions.

- [ ] All traffic over HTTPS, enforced at infrastructure level
- [ ] No secrets in code or git history — environment variables only
- [ ] `.env.example` committed with all required keys, no values
- [ ] Magic link tokens: single-use, 15-minute expiry, cryptographically random
- [ ] Access tokens: never stored in localStorage or DOM
- [ ] Refresh tokens: HttpOnly Secure SameSite=Lax cookie only (Lax, not Strict, so the session survives an OAuth-provider return — see §5.10 / MYS-91)
- [ ] Rate limiting on magic link requests
- [x] Tenant isolation — players can only access their own league data. Enforced at the **application layer** (authorization checks + cross-tenant isolation tests, MYS-48), not Postgres row-level security. True PG RLS remains an optional future defense-in-depth layer, not a launch requirement.
- [ ] Input sanitization on all text fields (submission notes, display names)
- [ ] Account deletion cascades to all personal data — no orphaned records
- [ ] "Log out of all devices" invalidates all refresh tokens
- [ ] Odesli API key stored server-side only, never exposed to client
- [ ] Dependency audit before launch (pip audit, npm audit)

---

## 10. Privacy Architecture

Aligned with commitments in `problem-statement.md`.

- No analytics pipelines that store individual user behavior by default
- Aggregate-only metrics at launch (total leagues, total rounds, total submissions — no user-level tracking)
- Individual taste profiles are a future opt-in feature — the data collection layer is not built until that feature is explicitly scoped
- Right to be forgotten: `DELETE /users/me` cascades to all submissions, votes, notes, sessions, and league membership records. Soft delete with a scheduled hard purge within 30 days.
- No third-party analytics scripts (no Google Analytics, no Mixpanel) in v1
- Ad provider must be vetted for political content policy before any ad integration is implemented
- **Subprocessors (GDPR Art. 28, MYS-184):** two third parties process personal data on our behalf — Resend (email addresses, for magic links/notifications) and DigitalOcean (hosts the app servers and database). Both have a standard DPA covering their processing. The song-lookup/playback integrations (Spotify, YouTube, Apple Music, Deezer) only ever receive a title/artist/ISRC — never anything tying a lookup back to a specific user — so they are not subprocessors of personal data. Keep this section in sync with the Privacy Policy's "subprocessors" section (`frontend/src/pages/PrivacyRoute.tsx`).

---

## 11. Environment Variables

All secrets and configuration are environment variables. Never committed to git.

```
# Backend
DATABASE_URL
SECRET_KEY                  (JWT signing key)
RESEND_API_KEY
ODESLI_API_KEY
ALLOWED_ORIGINS             (CORS)
ENVIRONMENT                 (development | production)
APP_BASE_URL                (base URL used to build magic-link URLs in emails)

# Frontend
VITE_API_BASE_URL
```

A `.env.example` file with all keys and no values is committed to the repo root.

---

## 12. Out of Scope for Technical Design v1

These are deferred and will require their own technical specs when scoped:

- Native mobile apps
- Push notifications (email only for v1)
- Taste profile data pipeline
- Crowd-sourced round theme voting
- Additional streaming platform integrations beyond Spotify, YouTube, Deezer
- Export / playlist copy features
- AI features of any kind

---

*This document is the authoritative technical specification for MysteryMixClub MVP. Claude Code should read `docs/` in full before beginning any build work, starting with `README.md`.*
