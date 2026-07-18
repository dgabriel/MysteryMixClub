# MysteryMixClub — Claude Code Context

## On Every Session Start

Run these steps before writing any code:

1. **Read the docs**
   ```
   read docs/design/style-guide.md
   read docs/technical/technical-design.md
   read docs/git-hygiene.md
   ```
   Do not proceed with any frontend work without having read the style guide.
   Do not proceed with any backend/architecture work without having read the technical design.
   Do not touch git (branch, commit, push, merge, rebase) without having read the
   git hygiene guide. These rules are non-negotiable — never improvise around a git mess.

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
| Sage        | `#506755` | Primary accent                              |
| Sage Light  | `#A8C4AD` | Secondary accent                            |
| Sage Pale   | `#D4E3D7` | Backgrounds, hover states                   |
| Rust        | `#B5533C` | **Signal color. One use per screen. Never decorative.** |
| Gold        | `#C9A028` | Achievement signal — winner/most-noted reveals only |
| Vinyl       | `#6B7EB5` | Avatar illustrations only (the 5 hardware icons) |
| Muted       | `#6D6A66` | Supporting text                             |
| Border      | `#D6D2CA` | Dividers, input underlines, card borders    |

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
| `main`        | **production** (`mysterymixclub-prod`, DO App Platform) | push → `deploy-prod.yml` (manual approval gate) |
| `develop`     | **staging** (DO **Droplet**, IaaS) | push → `deploy-staging.yml` SSHes in and runs `scripts/deploy-staging.sh` |
| `feature/*`   | nothing — open a PR        | PR → `develop` runs `ci.yml`         |

Flow: branch `feature/*` off `develop` → PR into `develop` (CI must pass) →
merge deploys to staging → PR `develop` → `main` → approve → deploys to prod.

> **Note — environments diverge.** Staging runs on a self-managed Ubuntu Droplet
> (Nginx + systemd + local Postgres); production still runs on DO App Platform.
> Staging setup/runbook: `docs/staging-setup.md`. The `.do/app.staging.yaml` spec
> is retained for reference but is **not** used by the staging deploy.

**Local hook chain** (Husky v9, `core.hooksPath=.husky/_`)

- `pre-commit` → `lint-staged`: ESLint `--fix` + Prettier on staged `*.ts/tsx`;
  `ruff check --fix` + `ruff format` on staged `*.py`.
- `commit-msg` → `commitlint` enforces Conventional Commits (`.commitlintrc.json`).
- `pre-push` → frontend `typecheck` + backend `pytest`.

Re-install hooks after a fresh clone with `npm install` (runs `prepare` → `husky`).

**Config as code**

- `.github/workflows/` — `ci.yml`, `deploy-staging.yml`, `deploy-prod.yml`.
- **Staging (Droplet):** `scripts/bootstrap-droplet.sh` (one-time provision),
  `scripts/deploy-staging.sh` (deploy), `scripts/mysterymixclub-api.service`
  (systemd), `scripts/nginx-mysterymixclub-staging.conf` (Nginx),
  `scripts/staging.env.example` (runtime env template). Runbook in
  `docs/staging-setup.md`. Deploy needs GitHub secrets `STAGING_HOST`,
  `STAGING_SSH_USER`, `STAGING_SSH_KEY`.
- **Prod (App Platform):** `.do/app.prod.yaml` — DO App Platform spec (api
  service + frontend static site + managed Postgres 15). `deploy-prod.yml` stages
  it into `.do/app.yaml` (gitignored) before deploying; needs
  `DIGITALOCEAN_ACCESS_TOKEN`. `.do/app.staging.yaml` is retained for reference
  only (staging moved to the Droplet).

**Adding a new secret**

Staging and prod take secrets by **different routes** — staging is a Droplet,
prod is App Platform. Doing only one leaves the other silently unconfigured,
which for an optional integration looks like "the feature doesn't work" rather
than an error.

1. Add the key to `.env.example` (no value) so the contract is documented.
2. **Staging (Droplet):** add the key to `scripts/staging.env.example` (no
   value); set the real value in `/etc/mysterymixclub/staging.env` on the
   Droplet, then `sudo systemctl restart mysterymixclub-api` — settings are
   cached per process, so editing the file alone changes nothing.
3. **Prod (App Platform):** add an `envs:` entry to `.do/app.prod.yaml`
   (`type: SECRET`) and set its value in the DO dashboard or via
   `doctl apps update`. `.do/app.staging.yaml` is reference-only and is **not**
   used by the staging deploy — adding a secret there has no effect.
4. Only if a *workflow* needs it (not the app at runtime): GitHub → Settings →
   Secrets and variables → Actions.
5. Never commit real secret values. The only pipeline secret today is
   `DIGITALOCEAN_ACCESS_TOKEN`.

Worked example (Apple Music): `docs/ci-cd.md` → "Adding a new secret";
`docs/staging-setup.md` → "Enabling Apple Music".

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
  git-hygiene.md            ← Read before ANY git work. Non-negotiable git rules
  feature-flags.md          ← Env-driven feature flags: registry + how to add one
  security/
    breach-notification-runbook.md  ← What to do if user data is exposed (MYS-187)
    data-residency.md         ← DO hosting region + EU transfer safeguard (MYS-188)
```

---

## Session Checklist

- [ ] Read `docs/design/style-guide.md`
- [ ] Read `docs/technical/technical-design.md`
- [ ] Read `docs/git-hygiene.md`
- [ ] Fetched active Linear issues
- [ ] Confirmed which issue we're working on today
- [ ] Stated one-sentence sprint goal back to user
