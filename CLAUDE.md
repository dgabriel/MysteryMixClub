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

2. **Sync, then load your sprint**
   Use bd, not Linear — Linear is retired for this project. Pull first so you're
   not working off a stale set of issues if another clone/session closed or
   created any since your last session:
   ```
   bd dolt pull
   bd ready
   bd list --status=in_progress
   ```
   `bd dolt pull` only merges remote issue state into your local DB — it doesn't
   push or touch git branches, so it's safe to run unconditionally, unlike
   `bd dolt push` (see the Beads Agent Context Profiles below for when that's
   allowed). Summarize the active sprint in one sentence, then list the
   in-scope issues before asking what to work on.

3. **Confirm before acting**
   State what you're about to do and which issue it maps to.
   If it doesn't map to an open bd issue, flag it.

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
- **One issue at a time.** Reference the bd issue ID in your first message (e.g. `MysteryMixClub-s7bv2t`); if it has a historical `MYS-##` number, mention that too for continuity.
- **State assumptions explicitly.** If something is ambiguous, say what you're assuming before acting.
- **No placeholder logic.** If you'd write a `// TODO`, ask instead.
- **Flag design drift.** If a request would violate the style guide, say so before proceeding.
- **Close bd issues when done.** When an issue is complete, run `bd close <id>` (see the Beads section below for the full session-close protocol).
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
| `main`        | **production** (self-managed **Droplet**, IaaS) | push → `deploy-prod.yml` (manual approval gate) → self-hosted runner on the prod Droplet runs `scripts/deploy-prod.sh` |
| `develop`     | **staging** (self-managed DO **Droplet**, IaaS) | push → `deploy-staging.yml` → self-hosted runner on the staging Droplet runs `scripts/deploy-staging.sh` |
| `feature/*`   | nothing — open a PR        | PR → `develop` runs `ci.yml`         |

Flow: branch `feature/*` off `develop` → PR into `develop` (CI must pass) →
merge deploys to staging → PR `develop` → `main` → approve → deploys to prod.

> **Prod's migration off App Platform is done (ADR 0002, MYS-225 shipped
> 2026-07-23).** Production now runs the same self-managed pattern as staging
> (Nginx + systemd + local Postgres) on its own Droplet, provisioned via
> Terraform (`infra/terraform/envs/prod/`). `.do/app.prod.yaml` (the old App
> Platform spec) has been deleted, not just deprecated. Both `deploy-staging.yml`
> and `deploy-prod.yml` run directly **on** their target Droplet via a
> self-hosted GitHub Actions runner — neither one uses SSH or GitHub secrets
> at all; `STAGING_HOST`/`STAGING_SSH_USER`/`STAGING_SSH_KEY` and
> `PROD_HOST`/`PROD_SSH_USER`/`PROD_SSH_KEY` were an earlier design and were
> never actually needed once the self-hosted-runner approach shipped (MYS-224
> for staging, MYS-225 for prod). Staging setup/runbook: `docs/staging-setup.md`;
> prod runbook: `docs/prod-setup.md`. The `.do/app.staging.yaml` spec is
> retained for reference but is **not** used by the staging deploy.

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
  `docs/staging-setup.md`. Deploy runs via a self-hosted GitHub Actions runner
  registered on the Droplet itself — no GitHub secrets needed.
- **Prod (Droplet, cut over 2026-07-23 — MYS-225):** `scripts/bootstrap-droplet-prod.sh`
  (one-time provision), `scripts/deploy-prod.sh` (deploy),
  `scripts/mysterymixclub-api-prod.service` (systemd, installed as
  `mysterymixclub-api.service`), `scripts/nginx-mysterymixclub-prod.conf`
  (Nginx, real Let's Encrypt cert, no basic auth), `scripts/prod.env.example`
  (runtime env template). Runbook in `docs/prod-setup.md`. Deploy runs via a
  self-hosted GitHub Actions runner registered on the prod Droplet itself — no
  GitHub secrets needed. Infra itself is Terraform: `infra/terraform/envs/prod/`.
  `.do/app.prod.yaml` (old App Platform spec) has been deleted.

**Adding a new secret**

Staging and prod take secrets by the **same route** — both are Droplets
(ADR 0002).

1. Add the key to `.env.example` (no value) so the contract is documented.
2. **Staging (Droplet):** add the key to `scripts/staging.env.example` (no
   value); set the real value in `/etc/mysterymixclub/staging.env` on the
   Droplet, then `sudo systemctl restart mysterymixclub-api` — settings are
   cached per process, so editing the file alone changes nothing.
3. **Prod (Droplet):** add the key to `scripts/prod.env.example`
   (no value); set the real value in `/etc/mysterymixclub/prod.env` on the prod
   Droplet, then `sudo systemctl restart mysterymixclub-api`. Same mechanism as
   staging, different box, different secret values — never share a value
   (`SECRET_KEY` especially) across environments. Never SSH into the prod
   Droplet yourself to do this — it goes through whoever holds prod access,
   not an ad hoc session.
4. Only if a *workflow* needs it (not the app at runtime): GitHub → Settings →
   Secrets and variables → Actions.
5. Never commit real secret values. `DIGITALOCEAN_ACCESS_TOKEN` is needed only
   for `terraform apply`, not for app deploys — neither deploy workflow uses
   SSH or GitHub secrets at all (self-hosted runners on each Droplet).

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
- [ ] Ran `bd dolt pull`, then fetched active bd issues
- [ ] Confirmed which issue we're working on today
- [ ] Stated one-sentence sprint goal back to user


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:970c3bf2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
