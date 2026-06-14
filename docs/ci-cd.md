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

## Workflows

| File                              | On                        | Does                                                        |
|-----------------------------------|---------------------------|-------------------------------------------------------------|
| `.github/workflows/ci.yml`        | PR → `main` or `develop`  | Frontend lint/typecheck/test; backend ruff/mypy/pytest+cov  |
| `.github/workflows/deploy-staging.yml` | push → `develop`     | SSH to the staging Droplet → run `scripts/deploy-staging.sh` (`STAGING_HOST`/`STAGING_SSH_USER`/`STAGING_SSH_KEY`) |
| `.github/workflows/deploy-prod.yml`    | push → `main`        | `environment: production` approval gate → stage `app.prod.yaml` → `mysterymixclub-prod` (`DIGITALOCEAN_ACCESS_TOKEN`) |

The prod deploy uses `secrets.DIGITALOCEAN_ACCESS_TOKEN`; the staging deploy uses
the `STAGING_*` SSH secrets (see [`staging-setup.md`](staging-setup.md)).

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

| Secret                       | Used by                          | Where to get it                              |
|------------------------------|----------------------------------|----------------------------------------------|
| `DIGITALOCEAN_ACCESS_TOKEN`  | `deploy-prod.yml`                | DO → API → Tokens (write scope)              |
| `STAGING_HOST`               | `deploy-staging.yml`             | staging Droplet public IP / hostname         |
| `STAGING_SSH_USER`           | `deploy-staging.yml`             | `mysterymixclub`                             |
| `STAGING_SSH_KEY`            | `deploy-staging.yml`             | private deploy key for the Droplet (see `staging-setup.md`) |

### DigitalOcean app secrets

These are runtime app config, set per app in the DO dashboard or via
`doctl apps update <app-id> --spec .do/app.<env>.yaml` (then fill SECRET values in the UI):

| Key            | Type     | Notes                                              |
|----------------|----------|----------------------------------------------------|
| `DATABASE_URL` | SECRET   | bound to the managed Postgres component (`${db.DATABASE_URL}`) |
| `SECRET_KEY`   | SECRET   | JWT signing key — `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `ENVIRONMENT`  | GENERAL  | `production` / `staging`                           |
| `RESEND_API_KEY`, `ODESLI_API_KEY`, `ALLOWED_ORIGINS`, `APP_BASE_URL` | SECRET/GENERAL | see `.env.example` |

### Adding a new secret (the routine)

1. Document the key (no value) in `.env.example`.
2. Add it as a GitHub Actions secret **and/or** an `envs:` entry in **both**
   `.do/app.staging.yaml` and `.do/app.prod.yaml` (`type: SECRET` for sensitive values).
3. Set the real value in the DO dashboard or `doctl` — never commit it.

---

## Local quickstart

```bash
npm install                      # root: installs husky + commitlint, wires hooks
npm --prefix frontend install    # frontend deps
pip install -e "backend[dev]"    # backend deps (in a venv)
```

Then normal `git commit` / `git push` exercise the hook chain automatically.
