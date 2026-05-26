# MysteryMixClub

A platform-agnostic, emotionally inclusive music league for close-knit friend groups.

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

## Status

Currently in PDLC, Definition phase. Discovery complete. PRD complete. Technical design complete.  MVP build in progress
