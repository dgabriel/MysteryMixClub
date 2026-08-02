# MysteryMixClub — Technical Design

**Document type:** Technical Design  
**Status:** Living spec — v1 MVP shipped and in production; updated as features ship  
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
| Frontend | React + TypeScript | Component model fits the club/mystery-mix/submission UI; TypeScript enforces data contracts |
| Styling | Tailwind CSS | Fast to build with, consistent on mobile, no runtime overhead |
| PWA | Web App Manifest + Service Worker | Home screen install, offline shell, native-feel on mobile without App Store |
| Backend | Python / FastAPI | Async-first, fast, Pydantic validation built in, proven in previous iteration |
| Database | PostgreSQL | Relational model fits the data; row-level security enforced at DB layer |
| Auth | Magic link + password + Google OAuth, JWT + refresh tokens (ADR 0007) | Magic link is passwordless-by-default; password and Google Sign-In are additive alternatives on the same two-token session model |
| Email | Resend | Magic links and mystery-mix notifications; generous free tier; developer-friendly |
| Song identity | Keyless resolver chain — Deezer + iTunes + Apple Music catalog + YouTube Data API (§8) | Odesli's public API retired 2026-07-31 (MYS-81); ISRC (from Deezer) remains the canonical identity backbone |
| Hosting | DigitalOcean Droplet, self-managed (ADR 0002) | Migrated off App Platform 2026-07-23 (MYS-225) for cost/control; Nginx + systemd + local Postgres on both staging and prod |

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

### Password Flow (ADR 0007)

Additive — magic link above is unchanged, and an account with no
`password_hash` simply cannot sign in this way.

1. `POST /auth/register` creates a NEW account with `{email, password,
   invite_token}`. Same invite gate, user cap, and club-join as magic-link
   sign-up; email ownership is established by the invite rather than by
   receiving a link.
2. `POST /auth/login` takes `{email, password}` and issues a session
   identically to `/auth/verify` (access JWT + refresh cookie + `sessions` row).
   Wrong password, no password set, and unknown email all return one
   indistinguishable 401.
3. `POST /auth/forgot-password` mails a single-use, hashed, 30-minute reset
   token (`password_reset_tokens`, same pattern as `magic_link_tokens`), or
   silently sends nothing when the address has no password — same neutral
   response either way.
4. `POST /auth/reset-password` consumes the token (hard delete), sets the new
   hash, and invalidates every session for that user.

Passwords are hashed with argon2. The only password rule is length (8–128).

### Google Sign-In Flow (ADR 0007)

Standard OAuth authorization code. Off unless `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` are all set — both endpoints
404 otherwise, the same "hidden when unconfigured" behavior Apple Music uses.

1. `GET /auth/google/login` (optional `invite_token`) redirects to Google's
   consent screen. It mints a random nonce, puts it in both a signed 10-minute
   `state` token and an HttpOnly cookie, and carries `invite_token` inside the
   signed state so it survives the round-trip untampered.
2. `GET /auth/google/callback` verifies `state` and requires its nonce to match
   the cookie — signing alone would not stop login-CSRF, where an attacker
   feeds a victim a callback URL from a flow the attacker started. It then
   exchanges the code for an access token server-side and asks Google's
   `/userinfo` who it belongs to.
3. An unverified Google email is refused outright — it proves nothing about who
   owns the mailbox.
4. Account resolution, in order: an existing `users.google_id` signs straight
   in; otherwise a matching verified `users.email` gets `google_id` linked onto
   it **without an invite** (the account already exists and Google has just
   proven ownership of its address) — if that account already carries a
   *different* `google_id`, the new identity **replaces** it (a decided
   trade-off, not a bug: rejecting would lock out real Google
   Workspace/personal-account address collisions with no admin tooling to
   resolve them, and relinking doesn't raise the account's trust level, since
   reaching this branch already requires the same verified-email proof a
   magic-link sign-in accepts); otherwise a brand-new account is created under
   the ordinary invite gate and user cap.
5. Being a top-level browser navigation, the callback can't return a JSON access
   token. It sets the refresh cookie and redirects to `APP_BASE_URL/login`
   with a `?google=` outcome flag; the SPA's on-mount `/auth/refresh` turns that
   cookie into an access token, and `/login` bounces an authenticated user to
   `/home`. The access token is deliberately never put in the redirect URL,
   where it would land in history, referrers, and logs.

The refresh cookie is already `SameSite=Lax` (MYS-91) precisely so it survives
this cross-site return; the nonce cookie is Lax for the same reason.

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
- Rate limiting on `/auth/forgot-password` — same 5 per email per hour
- Brute-force protection on `/auth/login` — maximum 10 FAILED attempts per email
  per 15 minutes (`login_attempts`); a successful login or a password reset
  clears the bucket
- Password hashes: argon2, never returned to a client, cleared on account deletion
- Google identity: `google_id` cleared on account deletion, same as the
  password hash — a third-party identifier for someone who asked to be
  forgotten, and left uncleared it would also collide with that Google
  account's next sign-up (the resolution queries can't see a soft-deleted row)
- Password reset tokens: single-use, 30-minute expiry, hashed at rest,
  hard-deleted on use
- Google Sign-In: `state` is signed AND bound to an HttpOnly nonce cookie, so a
  flow can only be completed by the browser that started it; an unverified
  Google email is refused; the access token is never placed in a redirect URL
- All endpoints require authentication except `/auth/request`, `/auth/verify`,
  `/auth/login`, `/auth/register`, `/auth/forgot-password`,
  `/auth/reset-password`, `/auth/google/enabled`, `/auth/google/login`, and
  `/auth/google/callback`
- HTTPS enforced at the infrastructure level

---

## 6. Data Model

### users
```
id                  UUID PRIMARY KEY
email               TEXT UNIQUE NOT NULL
display_name        TEXT NOT NULL
preferred_service   TEXT (spotify | youtube | deezer)
password_hash       TEXT NULL (argon2; NULL for magic-link-only accounts — ADR 0007)
google_id           TEXT UNIQUE NULL (Google's `sub`; NULL until Google Sign-In is linked — ADR 0007)
created_at          TIMESTAMP
deleted_at          TIMESTAMP (soft delete for cascade handling, hard purge on schedule)
```
> *Participation mode is **per-club**, not per-user (MYS-112). The original
> `default_vibe_mode` column on `users` is dropped; the default lives on
> `clubs.default_vibe_mode` and the per-member setting on
> `club_members.vibe_mode`.*

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

### clubs
```
id                  UUID PRIMARY KEY
name                TEXT NOT NULL
description         TEXT
organizer_id        UUID REFERENCES users(id)
total_mixes         INTEGER NOT NULL
current_mix         INTEGER DEFAULT 0
state               TEXT (active | complete)
default_vibe_mode   BOOLEAN DEFAULT FALSE (admin-set default participation mode; seeds club_members.vibe_mode at join — MYS-112)
created_at          TIMESTAMP
completed_at        TIMESTAMP
```

### club_members
```
id                  UUID PRIMARY KEY
club_id             UUID REFERENCES clubs(id)
user_id             UUID REFERENCES users(id)
vibe_mode           BOOLEAN DEFAULT FALSE (per-club participation default; seeded from clubs.default_vibe_mode at join, toggleable anytime — MYS-112)
role                TEXT (admin | member) DEFAULT 'member', CHECK (role IN ('admin', 'member')) — co-organizer support (MYS-99). An "admin" member has full operational parity with the club's fixed organizer_id everywhere organizer checks apply (see §7 annotations below), except they can't be demoted via the role endpoint by anyone but another admin, and the fixed organizer's own row is never touched by it.
joined_at           TIMESTAMP
removed_at          TIMESTAMP
```

### invites
```
id                  UUID PRIMARY KEY
club_id             UUID REFERENCES clubs(id)
created_by          UUID REFERENCES users(id)
token               TEXT UNIQUE NOT NULL
email               TEXT (nullable — set only on a waitlist-issued invite, MYS-215)
expires_at          TIMESTAMP
created_at          TIMESTAMP
```
> `email`, when set, locks redemption to that one address (checked
> case-insensitively in `auth._load_valid_invite`); a mismatch reads as no
> invite at all, same neutral handling as a bad token. Null (every club and
> `POST /admin/invites` invite) keeps the original shareable-link behavior —
> anyone with the token can redeem it.

### mixes
```
id                  UUID PRIMARY KEY
club_id             UUID REFERENCES clubs(id)
mix_number          INTEGER NOT NULL
theme               TEXT (nullable — unset until the organizer names the mystery mix)
description         TEXT
state               TEXT (pending | open_submission | open_voting | closed)
submission_deadline TIMESTAMP
voting_deadline     TIMESTAMP
votes_per_player    INTEGER DEFAULT 3
created_at          TIMESTAMP
closed_at           TIMESTAMP
```

The full slate of mystery mixes is auto-generated in the `pending` state when a
club is created, one per `total_mixes` (default 6), numbered 1..N with no theme
yet. Editing a club's `total_mixes` reconciles the slate: raising it appends new
`pending` mixes; lowering it deletes the trailing mixes, which must all still
be `pending` (a started mystery mix cannot be removed). The lifecycle is
forward-only: `pending → open_submission → open_voting → closed`. Only one mix
per club may be active (`open_submission`/`open_voting`) at a time, enforced
when a mix opens. `theme` (nullable) and `description` are editable only while
a mix is `pending`; deadlines remain editable until the mix closes. A mix
cannot open — manually or via auto-advance — without a `theme` set (MYS-211).
Closing a non-final mix auto-opens the next `pending` mix *if it has a theme*;
if not, it's left `pending` (no active mix) and the organizer alone is emailed
to set one. Closing the final mix completes the club.

### submissions
```
id                  UUID PRIMARY KEY
mix_id              UUID REFERENCES mixes(id)
user_id             UUID REFERENCES users(id)
isrc                TEXT (nullable since MYS-201 — see source_key)
source_key          TEXT (nullable; source-only identity: youtube:<video id> | bandcamp:<artist>/<track> — MYS-201)
title               TEXT NOT NULL
artist              TEXT NOT NULL
album               TEXT
album_art_url       TEXT
platform_links      JSONB (assembled {platform: url} cross-service links, best-effort — §8)
youtube_video_id    TEXT (cached exact YouTube video id, resolved via YouTube Data API — MYS-78)
spotify_track_uri   TEXT (cached spotify:track:... URI, resolved from ISRC at playlist-create time — MYS-83)
note                TEXT (max 280 chars)
participation_mode  TEXT (playing | vibing) — per-mix mode; defaults at submit from club_members.vibe_mode, overridable per mix (MYS-112)
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
mix_id              UUID REFERENCES mixes(id)
voter_id            UUID REFERENCES users(id)
submission_id       UUID REFERENCES submissions(id)
created_at          TIMESTAMP
UNIQUE(voter_id, submission_id)
```
> *Voting is anonymous throughout `open_voting` — `voter_id` is never surfaced
> to other players before a mystery mix closes. Once `mixes.state == "closed"`,
> `GET /mixes/:id/results` reveals each submission's voters by name
> (MYS-173). This does not change vote casting or the anonymous voting
> playlist (§7 Mystery Mixes) — it only adds identity to the post-close reveal.*

### notes
```
id                  UUID PRIMARY KEY
mix_id              UUID REFERENCES mixes(id)
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

### password_reset_tokens
```
id                  UUID PRIMARY KEY
email               TEXT NOT NULL
token_hash          TEXT NOT NULL
expires_at          TIMESTAMP NOT NULL
created_at          TIMESTAMP
```
> Same pattern as `magic_link_tokens` (ADR 0007), minus the `used` flag: a
> matched token is hard-deleted on lookup, and that delete is what enforces
> single use. Only ever written for an address that actually has a password.

### login_attempts
```
id                  UUID PRIMARY KEY
email               TEXT NOT NULL
created_at          TIMESTAMP
```
> One row per FAILED `/auth/login` attempt, for brute-force rate limiting
> (ADR 0007). Indexed `(email, created_at)` — every read is "this email, inside
> the window". A successful login or password reset deletes that email's rows;
> anything left is trimmed after 24h by `app.jobs.purge_login_attempts`, since
> an attempt against an address that never signs in successfully has nothing
> else to clear it.

### waitlist_entries
```
id                  UUID PRIMARY KEY
email               TEXT UNIQUE NOT NULL
created_at          TIMESTAMP
invited_at          TIMESTAMP (nullable — set once an admin invites this entry)
invited_by          UUID REFERENCES users(id) (nullable)
```
> Temporary, pre-launch (MYS-215, `WAITLIST_ENABLED` flag — see
> `docs/feature-flags.md`). Not an invite and not a user account — a row only
> becomes a real signup when an admin acts on it, which mints a club-less
> platform invite like `POST /admin/invites` creates, but with `email` locked
> to this entry's address, and emails it, stamping `invited_at`/`invited_by`.
> Resendable: inviting an already-invited row mints a fresh invite and
> re-stamps both fields, since the 48h invite link may have expired unused.
> Email stored lowercased.

---

## 7. API Design

All endpoints are prefixed `/api/v1/`. All responses are JSON. All authenticated endpoints require a valid JWT access token in the `Authorization: Bearer` header.

> **Wire vocabulary vs. route-layer field names (MYS-196).** The JSON wire
> speaks club/mix (`club_id`, `mix_number`, `total_mixes`, `current_mix`, …),
> but the API route layer's Pydantic request/response field names were
> deliberately kept on the old league/round vocabulary — this is a permanent
> split, not a transitional seam left over from the rename. Every
> request/response model inherits `WireModel` (`backend/app/api/wire.py`),
> whose alias generator translates exactly the renamed fields on the way in
> and out; everything else passes through unchanged. Route paths below use a
> generic `:id` placeholder, so this only matters if you're reading the OpenAPI
> schema or the Python route handlers directly.

### Auth
```
POST   /auth/request          Request a magic link (email in body)
GET    /auth/verify           Validate magic link token, issue session
POST   /auth/login            Sign in with email + password, issue session
POST   /auth/register         Create an invite-gated account with a password, issue session
POST   /auth/forgot-password  Email a single-use password reset link
POST   /auth/reset-password   Consume a reset token, set a new password
GET    /auth/google/enabled   Whether Google Sign-In is configured (public, ADR 0007)
GET    /auth/google/login     Redirect to Google's consent screen (404 when unconfigured)
GET    /auth/google/callback  Google's redirect back; issue session, bounce to the SPA
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

### Clubs
```
POST   /clubs               Create a new club (organizer sets default_vibe_mode — MYS-112)
GET    /clubs               Get all clubs for current user
GET    /clubs/:id           Get club detail
PATCH  /clubs/:id           Update club (organizer only: name, total_mixes, default_vibe_mode — co-organizers now have parity, MYS-99)
GET    /clubs/:id/members   Get club members
PATCH  /clubs/:id/membership Set the caller's own vibe_mode for the club (MYS-112)
DELETE /clubs/:id/members/:userId   Remove a member (organizer only — co-organizers now have parity, MYS-99)
PATCH  /clubs/:id/members/:userId/role  Promote/demote an active member to/from co-organizer (organizer or co-organizer only; MYS-99)
```

### Invites
```
POST   /clubs/:id/invites     Generate invite link (organizer or co-organizer only — MYS-246)
GET    /invites/:token        Validate invite token, return club preview
POST   /invites/:token/accept Join club via invite
```

### Admin
```
GET    /admin/users                    Search live accounts by email substring (platform-admin)
DELETE /admin/users/:id                Hard-delete an account and all its data (platform-admin, MYS-128)
POST   /admin/invites                  Generate a club-less signup invite (platform-admin, MYS-182)
GET    /admin/waitlist                 List waitlist entries, oldest first (platform-admin, MYS-215)
POST   /admin/waitlist/:id/invite      Mint + email an email-locked platform invite for a waitlist entry (platform-admin, MYS-215)
GET    /admin/metrics                  Platform-wide aggregate snapshot: users, clubs, mixes, submissions, votes, notes, waitlist -- aggregate-only, no user-level data (platform-admin, MysteryMixClub-etz7.1)
GET    /admin/metrics/signups?days=N   Daily signup counts over the last N UTC days, zero-filled (default 30, max 365; platform-admin, MysteryMixClub-etz7.2)
```

### Waitlist
```
GET    /waitlist/enabled      Whether the waitlist is currently on (public, MYS-215)
POST   /waitlist               Join the waitlist (public, MYS-215) — 404 while WAITLIST_ENABLED
                                is off, 409 on a duplicate email, 429 past 5/hour per IP
```

### Mystery Mixes
```
POST   /clubs/:id/mixes       Create a new mystery mix (organizer only — co-organizers now have parity, MYS-99)
GET    /clubs/:id/mixes       Get all mystery mixes for a club
GET    /mixes/:id             Get mystery mix detail
PATCH  /mixes/:id             Update mystery mix (organizer only: theme, deadlines, state — co-organizers now have parity, MYS-99)
GET    /mixes/:id/playlist    Get mystery mix playlist with cross-platform links (§8)
GET    /mixes/:id/results     Get mystery mix results (scores, Most Noted, vote breakdown, per-song voter identity once closed — MYS-173)
```

### Submissions
```
POST   /mixes/:id/submissions      Submit a song
GET    /mixes/:id/submissions/mine Get current user's submission for a mystery mix
GET    /mixes/:id/submissions      Get all submissions (available after voting closes)
```

### Song Search & Resolution
```
GET    /songs/search?q=        Search via Deezer (keyless, §8)
POST   /songs/resolve          Resolve a pasted link to canonical track
```

### Votes & Notes
```
POST   /mixes/:id/votes         Cast votes (Playing players only)
GET    /mixes/:id/votes/mine    Get current user's votes
POST   /submissions/:id/notes   Leave a note on a submission
GET    /submissions/:id/notes   Get notes on a submission
```

---

## 8. Song Identity & Cross-Platform Link Resolution

Odesli (Songlink) was the original dependency for platform-agnostic song
identity, but retired its public API 2026-07-31 (announced 2026-05-21).
Migrated off it 2026-06-22 (MYS-81), ahead of the deadline — Odesli is not
called anywhere in the current codebase. Song identity and cross-service
links are instead assembled from several keyless (and, where a token is
configured, keyed) per-platform sources.

### Search
`GET /songs/search` (`app/routers/songs.py`) searches Deezer by title
(+ optional artist) via `DeezerSearchClient`
(`app/services/deezer_search.py`), keyless. Returns title/artist/ISRC/album/
cover for the player to pick from.

### Paste-a-link resolution
`POST /songs/resolve` identifies a pasted platform URL via `LinkResolver`
(`app/services/link_resolver.py`, keyless). A submission requires an ISRC,
and only Deezer returns one keyless, so every platform's identity funnels
through a Deezer lookup:

- **Deezer** URL — direct `GET /track/{id}`, exact, no search needed.
- **Apple Music** URL — iTunes lookup for title/artist (no ISRC) → Deezer search.
- **Spotify** URL — oEmbed for track title only (no artist) → Deezer search on
  title alone; the weakest path, expected.
- **YouTube** URL — oEmbed's "Artist - Title (Official Video)"-style string,
  cleaned → Deezer search.
- **Bandcamp** URL — no oEmbed, no public API; OpenGraph `og:title` meta
  (`"Track Title, by Artist Name"`) parsed → Deezer search.

A caller can skip URL identification entirely by passing a known identity
(title/artist/isrc) straight from a search result.

### Cross-service link assembly
`SongLinkAssembler` (`app/services/song_links.py`, MYS-52) builds the
`{platform: url}` map persisted to `submissions.platform_links` — `spotify`,
`appleMusic`, `deezer`, `youtube`, `youtubeMusic`, `bandcamp` — from
per-platform lookups ranked against the query rather than trusted blindly
(MYS-175):

- **Deezer** — exact `/track/isrc:{isrc}` when an ISRC is known, else a
  ranked search; keyless.
- **Apple Music** — exact catalog link via `filter[isrc]` when a developer
  token is configured (MYS-106); otherwise, and on any miss, ranked keyless
  iTunes Search.
- **YouTube** — exact video link via the YouTube Data API when a resolver is
  configured (ranked, MYS-175), cached on `submissions.youtube_video_id`;
  falls back to a search deep link when unconfigured or unmatched.
  YouTube Music serves the same resolved video id.
- **Spotify** — deep link only (keyless); `submissions.spotify_track_uri` is
  resolved separately, lazily, at playlist-create time (MYS-83).
- **Bandcamp** — deep link only; Bandcamp's API is partner-only, so there is
  nothing keyless to resolve an exact link against.

Every platform always gets at least a deep link; a failed lookup falls back
to the deep link rather than raising (best-effort throughout).

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
- [x] Tenant isolation — players can only access their own club data. Enforced at the **application layer** (authorization checks + cross-tenant isolation tests, MYS-48), not Postgres row-level security. True PG RLS remains an optional future defense-in-depth layer, not a launch requirement.
- [ ] Input sanitization on all text fields (submission notes, display names)
- [ ] Account deletion cascades to all personal data — no orphaned records
- [ ] "Log out of all devices" invalidates all refresh tokens
- [ ] Song-resolution credentials (Apple Music developer token, YouTube Data
      API key) stored server-side only, never exposed to client
- [ ] Dependency audit before launch (pip audit, npm audit)

---

## 10. Privacy Architecture

Aligned with commitments in `problem-statement.md`.

- No analytics pipelines that store individual user behavior by default
- Aggregate-only metrics at launch (total clubs, total mystery mixes, total submissions — no user-level tracking)
- Individual taste profiles are a future opt-in feature — the data collection layer is not built until that feature is explicitly scoped
- Right to be forgotten: `DELETE /users/me` cascades to all submissions, votes, notes, sessions, and club membership records. Soft delete with a scheduled hard purge within 30 days.
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
- Crowd-sourced mystery mix theme voting
- Additional streaming-platform *playlist-generation* integrations beyond
  Spotify, YouTube, and Apple Music (all three shipped). Deezer was explored
  and dropped (registration closed) — it remains in use only as a keyless
  search/identity source (§8), not a playlist-generation target
- Export / playlist copy features
- AI features of any kind

---

*This document is the authoritative technical specification for MysteryMixClub MVP. Claude Code should read `docs/` in full before beginning any build work, starting with `README.md`.*
