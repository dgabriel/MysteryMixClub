# MysteryMixClub

A platform-agnostic, emotionally inclusive music league for close-knit friend groups.

> **🎧 Live staging:** https://staging.mysterymixclub.com — email [dgabriel@gmail.com](mailto:dgabriel@gmail.com) for access.

---

## What This Is

MysteryMixClub is a music sharing and discovery game where friends submit songs around themed rounds, listen together, and respond. Competitively or not, depending on how they want to play.

It is built for the people who were left out of Music League: those who won't use Spotify on principle, those who felt punished by scoring, and those who just want to share music with people they love without it becoming a competition.

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
- [`docs/technical/technical-design.md`](docs/technical/technical-design.md): Stack, data model, API design *(coming soon)*

---

## Core Principles

1. **Platform-agnostic by conviction:** no player should compromise their values to participate
2. **Inclusion is a design constraint:** every decision is evaluated against the question: would this keep the Outsider in the room?
3. **Privacy by architecture:** no opt-out AI features, ever; right to be forgotten is absolute
4. **Resonance over consensus:** Most Noted exists because emotional response is as valid as taste alignment
5. **The community owns the experience:** round themes are crowd-sourced; the league belongs to everyone

---

## MVP in One Sentence

A web app where a friend group can run music league rounds across Spotify, YouTube, and Deezer, with a Just Vibing mode for players who want to participate without scoring, and a Most Noted mechanic that celebrates resonance alongside competition.

---

## Tech Stack

- Frontend: React / TypeScript
- Backend: Python / FastAPI
- Song identity: ISRC via Odesli/Songlink API
- Hosting: Digital Ocean

---

## Running Locally

**Prerequisites:** Python 3.11+, Node 20+, Docker (for Postgres).

### 1. Start Postgres

```bash
docker compose up -d db
```

Brings up Postgres on `localhost:5432` (user `mmc`, password `mmc`, database
`mysterymixclub`).

### 2. Configure environment

```bash
cp .env.example backend/.env
```

The backend reads `backend/.env`. At minimum set:

```
DATABASE_URL=postgresql+asyncpg://mmc:mmc@localhost:5432/mysterymixclub
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(64))">
```

`RESEND_API_KEY` / `ODESLI_API_KEY` can stay empty for local work. The frontend
defaults to `http://localhost:8000`, so it needs no `.env` for the standard setup.

### 3. Backend (FastAPI)

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

### 4. Frontend (React / Vite)

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

| Branch      | Deploys to                      | Trigger                          |
|-------------|---------------------------------|----------------------------------|
| `feature/*` | nothing (open a PR)             | PR → `develop` runs CI           |
| `develop`   | staging (`mysterymixclub-staging`) | merge → auto-deploys          |
| `main`      | production (`mysterymixclub-prod`) | merge → manual approval gate  |

Flow: branch `feature/*` off `develop` → PR into `develop` (CI must pass) →
merge ships to staging → PR `develop` → `main` → approve → ships to prod.

Full details — git hooks, GitHub Actions, DigitalOcean App Platform specs, and
how to add a secret — are in [`docs/ci-cd.md`](docs/ci-cd.md).

---

## Status

PDLC Definition phase complete (Discovery, PRD, and technical design all done).
**MVP build in progress.**

- **Sprint 1 — Auth:** complete (magic-link sign-in, JWT sessions).
- **Sprint 2 — League & Member Management ([MYS-11](https://linear.app/mysterymixclub/issue/MYS-11), in progress):**
  create / read / manage league endpoints, invite + join flow, and the league
  and invite frontend screens are all merged (MYS-12, 13, 14, 34, 35, 15).
  Open follow-ups in the backlog: MYS-32 (harden join race), MYS-36 (re-home
  "log out of all devices").

Work is tracked in Linear (team **MysteryMixClub**, project **MysteryMixClub
MVP**). `develop` leads `main`; staging carries the un-promoted Sprint 2 work.
