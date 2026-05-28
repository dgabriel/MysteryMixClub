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
10. Refresh token is stored in an HttpOnly, Secure, SameSite=Strict cookie

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
default_vibe_mode   BOOLEAN DEFAULT FALSE
created_at          TIMESTAMP
deleted_at          TIMESTAMP (soft delete for cascade handling, hard purge on schedule)
```

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
created_at          TIMESTAMP
completed_at        TIMESTAMP
```

### league_members
```
id                  UUID PRIMARY KEY
league_id           UUID REFERENCES leagues(id)
user_id             UUID REFERENCES users(id)
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
theme               TEXT NOT NULL
state               TEXT (open_submission | open_voting | closed)
submission_deadline TIMESTAMP
voting_deadline     TIMESTAMP
votes_per_player    INTEGER DEFAULT 3
created_at          TIMESTAMP
closed_at           TIMESTAMP
```

### submissions
```
id                  UUID PRIMARY KEY
round_id            UUID REFERENCES rounds(id)
user_id             UUID REFERENCES users(id)
isrc                TEXT NOT NULL
title               TEXT NOT NULL
artist              TEXT NOT NULL
album               TEXT
album_art_url       TEXT
odesli_data         JSONB (full Odesli response, for platform resolution at playback)
note                TEXT (max 280 chars)
participation_mode  TEXT (playing | vibing)
created_at          TIMESTAMP
```

### votes
```
id                  UUID PRIMARY KEY
round_id            UUID REFERENCES rounds(id)
voter_id            UUID REFERENCES users(id)
submission_id       UUID REFERENCES submissions(id)
created_at          TIMESTAMP
UNIQUE(voter_id, submission_id)
```

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
PATCH  /users/me              Update display name, preferred service, vibe mode default
DELETE /users/me              Delete account and all associated data (right to be forgotten)
```

### Leagues
```
POST   /leagues               Create a new league
GET    /leagues               Get all leagues for current user
GET    /leagues/:id           Get league detail
PATCH  /leagues/:id           Update league (organizer only: name, total_rounds)
GET    /leagues/:id/members   Get league members
DELETE /leagues/:id/members/:userId   Remove a member (organizer only)
```

### Invites
```
POST   /leagues/:id/invites   Generate invite link (organizer or member)
GET    /invites/:token        Validate invite token, return league preview
POST   /invites/:token/accept Join league via invite
```

### Rounds
```
POST   /leagues/:id/rounds    Create a new round (organizer only)
GET    /leagues/:id/rounds    Get all rounds for a league
GET    /rounds/:id            Get round detail
PATCH  /rounds/:id            Update round (organizer only: theme, deadlines, state)
GET    /rounds/:id/playlist   Get round playlist with Odesli universal links
GET    /rounds/:id/results    Get round results (scores, Most Noted, vote breakdown)
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

---

## 9. Security Checklist

These are non-negotiable requirements, not suggestions.

- [ ] All traffic over HTTPS, enforced at infrastructure level
- [ ] No secrets in code or git history — environment variables only
- [ ] `.env.example` committed with all required keys, no values
- [ ] Magic link tokens: single-use, 15-minute expiry, cryptographically random
- [ ] Access tokens: never stored in localStorage or DOM
- [ ] Refresh tokens: HttpOnly Secure SameSite=Strict cookie only
- [ ] Rate limiting on magic link requests
- [ ] Row-level security on PostgreSQL — players can only access their own league data
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
