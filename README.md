# MysteryMixClub

A platform-agnostic, emotionally inclusive music club for close-knit friend groups.

> **🎧 Live:** https://mysterymixclub.com (production) · https://staging.mysterymixclub.com (staging) — email [dgabriel@gmail.com](mailto:dgabriel@gmail.com) for access.

---

## What This Is

MysteryMixClub is a music sharing and discovery experience where friends submit songs around themed mystery mixes, listen together, and respond. Competitively or not, depending on how they want to play.

It is built to bring friends together in one place, no matter which streaming service they use, so they can share the music that delights them without it necessarily turning into a competition (unless they want it to).

---

## Start Here

All product and technical documentation lives in `docs/`. Read in order.

### Discovery
Establishes the problem, the users, and the competitive landscape. Read this before anything else.

- [`docs/discovery/problem-statement.md`](docs/discovery/problem-statement.md): The problem we're solving and why it matters
- [`docs/discovery/personas.md`](docs/discovery/personas.md): The real people we're building for
- [`docs/discovery/competitive-analysis.md`](docs/discovery/competitive-analysis.md): The landscape and where we win

### Definition
Defines what we're building and how.

- [`docs/prd/prd.md`](docs/prd/prd.md): Product requirements, user stories, features, and MVP scope
- [`docs/technical/technical-design.md`](docs/technical/technical-design.md): Stack, data model, API design

---

## Core Principles

1. **Platform-agnostic by conviction:** no player should compromise their values to participate
2. **Inclusion is a design constraint:** every decision is evaluated against the question: would this keep the Outsider in the room?
3. **Privacy by architecture:** no opt-out AI features, ever; right to be forgotten is absolute
4. **Resonance over consensus:** Most Noted exists because emotional response is as valid as taste alignment
5. **The community owns the experience:** mystery mix themes are crowd-sourced; the club belongs to everyone

---

## MVP in One Sentence

A web app where a friend group can run music club mystery mixes across Spotify, YouTube, Deezer, and Apple Music, with a casual mode for players who want to participate without scoring, and a Most Noted mechanic that celebrates resonance alongside competition.

---

## Tech Stack

- Frontend: React / TypeScript
- Backend: Python / FastAPI
- Song identity: ISRC, resolved via keyless provider lookups (Deezer + iTunes), with cross-service links assembled in-app
- Hosting: DigitalOcean — production and staging both run on self-managed Droplets (ADR 0002)

---

## Running Locally

### Quick start (recommended)

New here? Install [git](https://git-scm.com) and [Docker](https://docs.docker.com/get-docker/),
then:

```bash
git clone https://github.com/dgabriel/MysteryMixClub.git
cd MysteryMixClub
./scripts/dev-up.sh
```

`scripts/dev-up.sh` works on **macOS and Linux**: it checks for the tools you need
(git, Python 3.11+, Node 20+, Docker), offers to install anything missing, creates
`backend/.env`, pulls the latest code, and (re)starts the full stack — Postgres +
API + web — in the background. Re-run it anytime to update and restart; it stops the
previous instance first. Other commands:

```bash
./scripts/dev-up.sh check   # just verify/install tools, start nothing
./scripts/dev-up.sh logs    # tail the API + web logs
./scripts/dev-up.sh stop    # stop the API + web it started
```

Then open the web app at <http://localhost:5173>. The manual steps below do the
same thing by hand if you prefer.

### Manual setup

**Prerequisites:** Python 3.11+, Node 20+, Docker (for Postgres).

#### 1. Start Postgres

```bash
docker compose up -d db
```

Brings up Postgres on `localhost:5432` (user `mmc`, password `mmc`, database
`mysterymixclub`).

#### 2. Configure environment

```bash
cp .env.example backend/.env
```

The backend reads `backend/.env`. At minimum set:

```
DATABASE_URL=postgresql+asyncpg://mmc:mmc@localhost:5432/mysterymixclub
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(64))">
```

The optional integration keys — `RESEND_API_KEY` (email), `YOUTUBE_API_KEY`, and
the `SPOTIFY_*` keys — can stay empty for local work; those features just degrade
gracefully (e.g. magic-link and notification emails print to the console instead
of sending). The frontend defaults to `http://localhost:8000`, so it needs no
`.env` for the standard setup. See [`docs/feature-flags.md`](docs/feature-flags.md)
for env-driven toggles like the staging email sink.

#### 3. Backend (FastAPI)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head          # apply migrations
uvicorn app.main:app --reload
```

- API: <http://localhost:8000>
- Interactive docs: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/api/v1/healthz>

> Sign-in is magic-link based. In development no email is sent — the link is
> printed to the **uvicorn console**. Watch the backend logs to grab it.

#### 4. Frontend (React / Vite)

```bash
cd frontend
npm install
npm run dev
```

App: <http://localhost:5173> (calls the API at `http://localhost:8000`).

---

## Testing Locally

**Backend** — tests run against a separate `mysterymixclub_test` database, which
`docker compose up -d db` creates automatically on first init (see
`docker/initdb/`). If you started Postgres before that script existed, create it
once by hand:

```bash
docker compose exec db psql -U mmc -d mysterymixclub \
  -c "CREATE DATABASE mysterymixclub_test;"
```

Then:

```bash
cd backend && source .venv/bin/activate
pytest                 # full suite
pytest --cov=app       # with coverage
```

**Frontend:**

```bash
cd frontend
npm test               # vitest, single run
npm run test:watch     # watch mode
npm run typecheck      # tsc
npm run lint           # eslint
```

The same checks run in CI (`ruff` · `mypy` · `pytest` for backend; `lint` ·
`typecheck` · `test` for frontend) on every PR into `develop`.

---

## Deploying

Deploys are **automated through the pipeline — you do not deploy by hand.**

| Branch      | Deploys to                          | Trigger                          |
|-------------|-------------------------------------|----------------------------------|
| `feature/*` | nothing (open a PR)                 | PR → `develop` runs CI           |
| `develop`   | staging (self-managed DO **Droplet**) | merge → auto-deploys via SSH   |
| `main`      | production (self-managed DO **Droplet**, `mysterymixclub-prod`) | merge → manual approval gate, then auto-deploys via SSH |

> Staging and production run the same self-managed pattern — Ubuntu Droplet,
> Nginx + systemd + local Postgres (ADR 0002: [`docs/adr/0002-prod-platform-self-managed-droplet.md`](docs/adr/0002-prod-platform-self-managed-droplet.md)).
> Runbooks: [`docs/staging-setup.md`](docs/staging-setup.md) /
> [`docs/prod-setup.md`](docs/prod-setup.md).

Flow: branch `feature/*` off `develop` → PR into `develop` (CI must pass) →
merge ships to staging → PR `develop` → `main` → approve → ships to prod.

Full details — git hooks, GitHub Actions, and how to add a secret — are in
[`docs/ci-cd.md`](docs/ci-cd.md).

---

## Status

PDLC Definition phase complete (Discovery, PRD, and technical design all done).
**MVP build is well underway** — the end-to-end club loop runs. Merged on
`develop`:

- **Auth:** magic-link sign-in, JWT + refresh-token sessions, log-out-of-all-devices, account deletion.
- **Clubs:** create / read / manage, member management, invite + join flow (with frontend screens).
- **Mystery mixes:** auto-generated mix slate, forward-only state machine (pending → submission → voting → closed), organizer controls, auto-advance to the next mix on close.
- **Submissions:** paste-a-link and search, ISRC resolution, and cross-service playback links (Spotify, YouTube, Deezer, Apple Music) assembled keyless.
- **Voting & scoring:** voting with a configurable per-mix budget, competitive/casual mode, self-vote prevention, anonymous shuffled playlist, the **Most Noted** mechanic, results / reveal, and post-reveal notes players can leave on any submission (one per song, editable while voting is still open).
- **Playlist generation:** one-click YouTube playlist link (keyless), a shared-account Spotify saved playlist (one ops-connected account, linked via a one-time OAuth flow — MYS-169/234), and per-player Apple Music library playlists via MusicKit (each member builds their own copy; Apple has no API path to a shareable link, so this is intentionally not Spotify parity). Deezer playlist creation is a confirmed dead end — links only.
- **Notifications:** mystery-mix-lifecycle email notifications (Resend, with inbound-mail forwarding) with per-user preference + one-click unsubscribe.
- **Beta gate:** a pre-launch waitlist + email-locked invite flow exists end-to-end (currently dormant — off in every environment) alongside a permanent "beta" badge in the nav while the product is pre-wide-release.
- **Hardening:** security response headers, application-layer tenant isolation, and a WCAG 2.2 AA accessibility remediation pass (contrast, forms, semantics, keyboard, motion, touch targets).

Active work — Spotify shared-playlist expiration handling, a profile/settings screen
(photo upload), scaling strategy, observability, and a Doppler secrets-manager
migration, among others — is tracked in Linear (team **MysteryMixClub**, project
**MysteryMixClub MVP**). `develop` leads `main`; both `develop` and `main` deploy
automatically (staging and production respectively) on merge.
