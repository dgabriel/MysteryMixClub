# MysteryMixClub — Claude Code Context

## On Every Session Start

Run these steps before writing any code:

1. **Read the docs**
   ```
   read docs/design/style-guide.md
   read docs/technical/technical-design.md
   ```
   Do not proceed with any frontend work without having read the style guide.
   Do not proceed with any backend/architecture work without having read the technical design.

2. **Load your sprint**
   Use the Linear MCP to fetch your current issues:
   ```
   list issues from the MysteryMixClub team, filtered to In Progress and Todo
   ```
   Summarize the active sprint in one sentence, then list the in-scope issues
   before asking what to work on.

3. **Confirm before acting**
   State what you're about to do and which issue it maps to.
   If it doesn't map to an open Linear issue, flag it.

---

## Project

**MysteryMixClub** — platform-agnostic music league for close-knit friend groups.
Competitor to Music League. Multi-streaming-service support. Invite-only.

Stack: Python / FastAPI · React / TypeScript · Digital Ocean

---

## Design System — Non-Negotiable

Full spec: `docs/design/style-guide.md`

Quick reference (never override these without reading the full guide first):

| Token       | Value     | Usage                                      |
|-------------|-----------|---------------------------------------------|
| Cream       | `#F0EDE6` | Default background                          |
| Ink         | `#2E2B27` | Primary text                                |
| Sage        | `#7A9E82` | Primary accent                              |
| Sage Light  | `#A8C4AD` | Secondary accent                            |
| Sage Pale   | `#D4E3D7` | Backgrounds, hover states                   |
| Rust        | `#B5533C` | **Signal color. One use per screen. Never decorative.** |
| Muted       | `#8A8680` | Supporting text                             |

- Headings: `DM Serif Display`
- Everything else: `DM Mono`
- Inputs: underline style only — no border boxes
- Aesthetic: clean, compact, simple — Duchamp Rotorelief / concentric rings
- Tailwind: use named tokens (`text-ink`, `bg-sage`, etc.) — never raw hex in components

**Rust rule:** If you are about to use Rust a second time in one screen, stop and ask.

---

## Technical Architecture

Full spec: `docs/technical/technical-design.md`

Before scaffolding any new service, endpoint, or data model, read the relevant
section of the technical design. Do not introduce patterns not already established
unless you flag it first.

---

## Working Rules

- **Read before you write.** Always read a file before editing it. Never assume current state.
- **Smallest change that works.** Surgical edits only. No speculative refactors.
- **One issue at a time.** Reference the Linear issue identifier in your first message (`MMC-##`).
- **State assumptions explicitly.** If something is ambiguous, say what you're assuming before acting.
- **No placeholder logic.** If you'd write a `// TODO`, ask instead.
- **Flag design drift.** If a request would violate the style guide, say so before proceeding.
- **Update Linear when done.** When an issue is complete, note it so the status can be updated.

---

## CI/CD

Full spec: `docs/ci-cd.md`

**Branch model**

| Branch        | Deploys to                 | How                                  |
|---------------|----------------------------|--------------------------------------|
| `main`        | **production** (`mysterymixclub-prod`)    | push → `deploy-prod.yml` (manual approval gate) |
| `develop`     | **staging** (`mysterymixclub-staging`)    | push → `deploy-staging.yml` (auto)   |
| `feature/*`   | nothing — open a PR        | PR → `develop` runs `ci.yml`         |

Flow: branch `feature/*` off `develop` → PR into `develop` (CI must pass) →
merge deploys to staging → PR `develop` → `main` → approve → deploys to prod.

**Local hook chain** (Husky v9, `core.hooksPath=.husky/_`)

- `pre-commit` → `lint-staged`: ESLint `--fix` + Prettier on staged `*.ts/tsx`;
  `ruff check --fix` + `ruff format` on staged `*.py`.
- `commit-msg` → `commitlint` enforces Conventional Commits (`.commitlintrc.json`).
- `pre-push` → frontend `typecheck` + backend `pytest`.

Re-install hooks after a fresh clone with `npm install` (runs `prepare` → `husky`).

**Config as code**

- `.github/workflows/` — `ci.yml`, `deploy-staging.yml`, `deploy-prod.yml`.
- `.do/app.staging.yaml` / `.do/app.prod.yaml` — per-environment DO App Platform
  specs (api service + frontend static site + managed Postgres 15). Each deploy
  workflow stages its spec into `.do/app.yaml` (gitignored) before deploying.
  `deploy_on_push: false` — Actions own deploys.

**Adding a new secret**

1. Add the key to `.env.example` (no value) so the contract is documented.
2. GitHub → Settings → Secrets and variables → Actions → add the repo/environment secret.
3. If the app needs it at runtime, add an `envs:` entry in **both**
   `.do/app.staging.yaml` and `.do/app.prod.yaml` (`type: SECRET`) and set its
   value in the DO dashboard or via `doctl apps update`.
4. Never commit real secret values. The only pipeline secret today is
   `DIGITALOCEAN_ACCESS_TOKEN`.

---

## Docs Map

```
docs/
  design/
    style-guide.md          ← Read before ANY frontend work
    style-tile.html         ← Visual reference
  technical/
    technical-design.md     ← Read before ANY backend/arch work
  prd/                      ← Product requirements
  discovery/                ← Research and early decisions
  ci-cd.md                  ← Pipeline, branch model, onboarding secrets
```

---

## Session Checklist

- [ ] Read `docs/design/style-guide.md`
- [ ] Read `docs/technical/technical-design.md`
- [ ] Fetched active Linear issues
- [ ] Confirmed which issue we're working on today
- [ ] Stated one-sentence sprint goal back to user
