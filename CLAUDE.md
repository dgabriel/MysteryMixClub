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

**MysteryMixClub** — platform-agnostic music club for close-knit friend groups.
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
| Rust        | `#AD4F39` | **Signal color. One use per screen. Never decorative.** |
| Gold        | `#83681A` | Achievement signal — winner/most-noted reveals only |
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
- **Record every major decision as an ADR.** Full process: `docs/adr/README.md`.
  Applies to PM and developers alike, Claude Code included — a tech/vendor/hosting
  choice, an architectural pattern other work builds on, or any tradeoff that
  overrides the "obvious" approach gets a numbered ADR at decision time, not
  after the fact.

---

## CI/CD

Full spec: `docs/ci-cd.md`

**Branch model**

| Branch        | Deploys to                 | How                                  |
|---------------|----------------------------|--------------------------------------|
| `main`        | **production** (self-managed **Droplet**, IaaS — MYS-225, cutover pending) | push → `deploy-prod.yml` (manual approval gate) SSHes in and runs `scripts/deploy-prod.sh` |
| `develop`     | **staging** (DO **Droplet**, IaaS) | push → `deploy-staging.yml` SSHes in and runs `scripts/deploy-staging.sh` |
| `feature/*`   | nothing — open a PR        | PR → `develop` runs `ci.yml`         |

Flow: branch `feature/*` off `develop` → PR into `develop` (CI must pass) →
merge deploys to staging → PR `develop` → `main` → approve → deploys to prod.

> **Note — prod is mid-migration off App Platform.** Per **ADR 0002**
> (`docs/adr/0002-prod-platform-self-managed-droplet.md`), production moves to
> the same self-managed model as staging (Nginx + systemd + local Postgres) —
> `deploy-prod.yml` and the scripts below already target the Droplet, but no
> prod Droplet has actually been applied/cut over yet (MYS-225 tracks it;
> `PROD_HOST`/`PROD_SSH_USER`/`PROD_SSH_KEY` don't exist as secrets yet, so a
> push to `main` today would fail at the deploy step, not silently succeed
> against something stale). `.do/app.prod.yaml` is retained only until that
> cutover happens, then should be deleted outright, not kept as a fallback.
> Staging setup/runbook: `docs/staging-setup.md`; prod runbook:
> `docs/prod-setup.md`. The `.do/app.staging.yaml` spec is retained for
> reference but is **not** used by the staging deploy.

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
- **Prod (Droplet, MYS-225 — pending cutover):** `scripts/bootstrap-droplet-prod.sh`
  (one-time provision), `scripts/deploy-prod.sh` (deploy),
  `scripts/mysterymixclub-api-prod.service` (systemd, installed as
  `mysterymixclub-api.service`), `scripts/nginx-mysterymixclub-prod.conf`
  (Nginx, real Let's Encrypt cert, no basic auth), `scripts/prod.env.example`
  (runtime env template). Runbook in `docs/prod-setup.md`. Deploy needs GitHub
  secrets `PROD_HOST`, `PROD_SSH_USER`, `PROD_SSH_KEY` (not yet set — no prod
  Droplet exists yet). Infra itself is Terraform: `infra/terraform/envs/prod/`.
  `.do/app.prod.yaml` (old App Platform spec) is reference-only until cutover,
  then should be deleted.

**Adding a new secret**

Staging and prod now take secrets by the **same route** — both are Droplets
(ADR 0002). Until MYS-225's cutover, though, prod's route is theoretical: the
Droplet, its env file, and its systemd service don't exist yet.

1. Add the key to `.env.example` (no value) so the contract is documented.
2. **Staging (Droplet):** add the key to `scripts/staging.env.example` (no
   value); set the real value in `/etc/mysterymixclub/staging.env` on the
   Droplet, then `sudo systemctl restart mysterymixclub-api` — settings are
   cached per process, so editing the file alone changes nothing.
3. **Prod (Droplet, once cut over):** add the key to `scripts/prod.env.example`
   (no value); set the real value in `/etc/mysterymixclub/prod.env` on the prod
   Droplet, then `sudo systemctl restart mysterymixclub-api`. Same mechanism as
   staging, different box, different secret values — never share a value
   (`SECRET_KEY` especially) across environments.
4. Only if a *workflow* needs it (not the app at runtime): GitHub → Settings →
   Secrets and variables → Actions.
5. Never commit real secret values. Once MYS-225 ships, `DIGITALOCEAN_ACCESS_TOKEN`
   is needed only for `terraform apply`, not for app deploys — those go through
   `PROD_HOST`/`PROD_SSH_USER`/`PROD_SSH_KEY` instead, same shape as staging's
   `STAGING_*` secrets.

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
  adr/                      ← Architecture decision records (why, not just what)
    README.md               ← ADR process: who writes one, when, format
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
