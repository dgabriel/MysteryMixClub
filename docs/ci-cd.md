# CI/CD — MysteryMixClub

Configuration-as-code pipeline: Husky git hooks → GitHub Actions → DigitalOcean
App Platform. Everything here lives in the repo; nothing is clicked together by
hand except secrets and branch-protection rules (documented below).

---

## Pipeline diagram

```
 Developer machine                GitHub                         DigitalOcean
 ─────────────────                ──────                         ────────────

 git commit
   ├─ pre-commit  → lint-staged (eslint/prettier, ruff)
   └─ commit-msg  → commitlint (Conventional Commits)
        │
 git push
   └─ pre-push    → frontend typecheck + backend pytest
        │
        ▼
   ┌─────────────────────── feature/* ──────────────────────┐
   │  open PR → develop                                      │
   │     └─ ci.yml ──► frontend: lint · typecheck · test     │
   │                   backend:  ruff · mypy · pytest+cov    │
   └─────────────────────────────────────────────────────────┘
        │ merge
        ▼
   push to develop ─► deploy-staging.yml ─► ssh ─► scripts/deploy-staging.sh
                                              └─► staging Droplet (Nginx + systemd)
        │ PR develop → main, merge
        ▼
   push to main ───► deploy-prod.yml ─► [environment: production]
                          (manual approval gate)
                              └─► app_action/deploy ─► mysterymixclub-prod
```

---

## Branch model

| Branch        | Purpose            | Deploys to    | Trigger                          |
|---------------|--------------------|---------------|----------------------------------|
| `main`        | production-ready   | `mysterymixclub-prod` (DO App Platform) | push → `deploy-prod.yml` (gated) |
| `develop`     | integration        | staging **Droplet** (IaaS) | push → `deploy-staging.yml` (SSH) |
| `feature/*`   | one unit of work   | —             | PR → `develop` runs `ci.yml`     |

> **Staging and prod use different infrastructure.** Staging is a self-managed
> Ubuntu Droplet (Nginx + systemd + local Postgres); production is DO App
> Platform. Staging provisioning and the deploy contract are documented in
> [`staging-setup.md`](staging-setup.md). `.do/app.staging.yaml` is kept for
> reference but no longer drives the staging deploy.

Lifecycle: `feature/*` off `develop` → PR into `develop` (CI green required) →
merge auto-deploys staging → smoke-test staging → PR `develop` → `main` →
approve the `production` environment → prod deploy.

---

## Scheduled jobs

The backend ships two standalone jobs run outside the request path:
`python -m app.jobs.purge_accounts` (right-to-be-forgotten hard purge) and
`python -m app.jobs.advance_mixes` (deadline force-advance + 12h warnings,
MYS-145/162). On **staging** the deadline job runs every 15 minutes via a systemd
timer (`mysterymixclub-advance-mixes.timer`) — see
[`staging-setup.md` §7](staging-setup.md).

> **Prod follow-up (not yet wired).** Production runs on DO App Platform, which
> has no systemd; the deadline job must be scheduled there before deadline-based
> closing works in prod. Options: a DO App Platform **Job** component with a cron
> schedule (e.g. `*/15 * * * *`) running `python -m app.jobs.advance_mixes`
> against the managed Postgres, added to `.do/app.prod.yaml`; or an external
> scheduler hitting the same entrypoint. Until then, prod mystery mixes close on
> quorum only. Tracked as a deploy-prod follow-up to this PR.

---

## Workflows

| File                              | On                        | Does                                                        |
|-----------------------------------|---------------------------|-------------------------------------------------------------|
| `.github/workflows/ci.yml`        | PR → `main` or `develop`  | Frontend lint/typecheck/test; backend ruff/mypy/pytest+cov  |
| `.github/workflows/deploy-staging.yml` | push → `develop`     | Runs on a self-hosted runner living on the staging Droplet → `scripts/deploy-staging.sh` |
| `.github/workflows/deploy-prod.yml`    | push → `main`        | `environment: production` approval gate → self-hosted runner on the prod Droplet → `scripts/deploy-prod.sh` |

Both deploys run directly on their target Droplet via a self-hosted GitHub
Actions runner (MYS-224/225) — no SSH secrets or `DIGITALOCEAN_ACCESS_TOKEN`
needed for either one anymore. See [`staging-setup.md`](staging-setup.md) and
[`prod-setup.md`](prod-setup.md) for runner registration.

---

## Git hooks (Husky v9)

Installed via `npm install` at the repo root (the `prepare` script runs `husky`).
`git config core.hooksPath` points at `.husky/_`.

| Hook         | Runs                              | Blocks on                          |
|--------------|-----------------------------------|------------------------------------|
| `pre-commit` | `lint-staged`                     | ESLint/Prettier or ruff errors on staged files |
| `commit-msg` | `commitlint --edit`               | non-Conventional-Commit message    |
| `pre-push`   | `npm --prefix frontend run typecheck` + `pytest` | type errors or failing tests |

`lint-staged` config lives in the root `package.json`:

```
frontend/**/*.{ts,tsx}  → eslint --fix, prettier --write
backend/**/*.py         → ruff check --fix, ruff format
```

> The `pre-push` backend step needs the backend virtualenv active (or its deps
> installed) so `python -m pytest` resolves.

Conventional Commit types: `feat`, `fix`, `chore`, `ci`, `docs`, `refactor`,
`test`, `build`, `perf`, `style`, `revert`. Example: `feat(auth): add magic-link expiry`.

---

## Branch protection checklist (configure manually in GitHub)

GitHub → Settings → Branches → add rules:

**`main`**
- [ ] Require a pull request before merging (≥1 approval)
- [ ] Require status checks to pass: `Frontend (lint · typecheck · test)`, `Backend (ruff · mypy · pytest)`
- [ ] Require branches to be up to date before merging
- [ ] Require conversation resolution before merging
- [ ] Do not allow bypassing the above settings
- [ ] Restrict who can push (no direct pushes; merges only)

**`develop`**
- [ ] Require a pull request before merging
- [ ] Require the same CI status checks to pass
- [ ] Require branches to be up to date before merging

**Environments** (GitHub → Settings → Environments):
- [ ] `production` — add **required reviewers** (this is the prod approval gate)
- [ ] `staging` — no reviewers needed (auto-deploy)

---

## Secret setup (onboarding)

### GitHub Actions secrets

GitHub → Settings → Secrets and variables → Actions:

Neither deploy workflow needs GitHub Actions secrets anymore — both run
directly on their target Droplet via a self-hosted runner (see the workflows
table above). `DIGITALOCEAN_ACCESS_TOKEN` is only needed locally for
`terraform apply`, not by any workflow; `STAGING_HOST`/`STAGING_SSH_USER`/
`STAGING_SSH_KEY` were used by the old SSH-based `deploy-staging.yml` and are
no longer referenced (safe to delete from the `staging` environment's
secrets, or just leave them unused).

### DigitalOcean app secrets

These are runtime app config, set per app in the DO dashboard or via
`doctl apps update <app-id> --spec .do/app.<env>.yaml` (then fill SECRET values in the UI):

| Key            | Type     | Notes                                              |
|----------------|----------|----------------------------------------------------|
| `DATABASE_URL` | SECRET   | bound to the managed Postgres component (`${db.DATABASE_URL}`) |
| `SECRET_KEY`   | SECRET   | JWT signing key — `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `ENVIRONMENT`  | GENERAL  | `production` / `staging`                           |
| `RESEND_API_KEY`, `ODESLI_API_KEY`, `ALLOWED_ORIGINS`, `APP_BASE_URL` | SECRET/GENERAL | see `.env.example` |
| `APPLE_MUSIC_TEAM_ID`, `APPLE_MUSIC_KEY_ID`, `APPLE_MUSIC_PRIVATE_KEY` | SECRET | Apple Music (MYS-104). **All three or none** — any missing and the Apple UI hides itself and links fall back to keyless iTunes. Provisioning walkthrough in `staging-setup.md` → "Enabling Apple Music". |

### Adding a new secret (the routine)

**Staging and production take secrets by different routes** — staging is a
self-managed Droplet, production is App Platform. Doing only one leaves the other
silently unconfigured, which for optional integrations looks exactly like the
feature "not working" rather than an error.

1. Document the key (no value) in `.env.example`.
2. **Staging (Droplet):** add the key to `scripts/staging.env.example` (no
   value), then set the real value in `/etc/mysterymixclub/staging.env` on the
   Droplet and `sudo systemctl restart mysterymixclub-api`. Settings are cached
   per process, so an edit without the restart changes nothing.
3. **Production (App Platform):** add an `envs:` entry to `.do/app.prod.yaml`
   (`type: SECRET`), then set the value in the DO dashboard or via `doctl`.
4. If a *workflow* needs it (not the app at runtime), add it as a GitHub Actions
   secret instead.

> `.do/app.staging.yaml` is **reference only** — staging moved to the Droplet
> (MYS-39) and that spec is not used by the staging deploy. Adding a secret there
> has no effect; use step 2.

---

## Local quickstart

```bash
npm install                      # root: installs husky + commitlint, wires hooks
npm --prefix frontend install    # frontend deps
pip install -e "backend[dev]"    # backend deps (in a venv)
```

Then normal `git commit` / `git push` exercise the hook chain automatically.
