# CI/CD — MysteryMixClub

Configuration-as-code pipeline: Husky git hooks → GitHub Actions → self-hosted
runners on self-managed DigitalOcean Droplets (staging and production alike).
Everything here lives in the repo; nothing is clicked together by hand except
branch-protection rules and the one-time Droplet/runner provisioning
(documented below).

---

## Pipeline diagram

```
 Developer machine                GitHub                    DigitalOcean Droplets

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
   push to develop ─► deploy-staging.yml (self-hosted runner
                       living ON the staging Droplet) ──────► scripts/deploy-staging.sh
                                                               (Nginx + systemd)
        │ PR develop → main, merge (real merge commit only — see
        │ docs/git-hygiene.md "Why promotions must be a real merge";
        │ enforced by a GitHub ruleset on main, squash/rebase not offered)
        ▼
   push to main ───► deploy-prod.yml
                        ├─ build-frontend (hosted runner, ungated):
                        │    npm ci && npm run build → upload dist/ artifact
                        └─ deploy [environment: production, manual approval
                             gate] (self-hosted runner living ON the prod
                             Droplet) ──► download dist/ artifact
                                          → scripts/deploy-prod.sh
                                            (gunicorn+systemd graceful reload,
                                             publishes the CI-built frontend)
```

Prod's frontend build moved off the Droplet into CI (MYS-259) — the old
on-box `npm ci && npm run build` risked OOMing a 2 GB app host under load.
Staging still builds on-box; see `docs/prod-setup.md` "What changes vs.
staging" for why that gap exists and isn't (yet) closed.

Both deploy jobs that actually touch a Droplet run directly on it — no SSH from
GitHub, no DigitalOcean App Platform involved for either environment.

---

## Branch model

| Branch        | Purpose            | Deploys to    | Trigger                          |
|---------------|--------------------|---------------|----------------------------------|
| `main`        | production-ready   | prod **Droplet** (IaaS) | push → `deploy-prod.yml` (gated, self-hosted runner) |
| `develop`     | integration        | staging **Droplet** (IaaS) | push → `deploy-staging.yml` (self-hosted runner) |
| `feature/*`   | one unit of work   | —             | PR → `develop` runs `ci.yml`     |

> **Staging and prod now use the same infrastructure shape** (ADR 0002,
> MYS-225 shipped 2026-07-23): each is a self-managed Ubuntu Droplet (Nginx +
> systemd + local Postgres), provisioned via Terraform
> (`infra/terraform/envs/{staging,prod}/`). Provisioning and deploy contracts
> are documented in [`staging-setup.md`](staging-setup.md) and
> [`prod-setup.md`](prod-setup.md). `.do/app.staging.yaml` is kept for
> reference but no longer drives the staging deploy; the equivalent prod spec,
> `.do/app.prod.yaml`, has been deleted outright now that the cutover is done.

Lifecycle: `feature/*` off `develop` → PR into `develop` (CI green required) →
merge auto-deploys staging → smoke-test staging → PR `develop` → `main` →
approve the `production` environment → prod deploy.

---

## Scheduled jobs and background workers

The backend ships standalone processes run outside the request path, none of
them behind DO's own scheduler/App Platform equivalent — all systemd, on the
same self-managed Droplets as the API:

- **Timer-triggered (`oneshot` + `.timer`)**: `python -m app.jobs.purge_accounts`
  (right-to-be-forgotten hard purge), `python -m app.jobs.purge_login_attempts`
  (trims `login_attempts` rows older than 24h, ADR 0007), and
  `python -m app.jobs.advance_mixes`
  (deadline force-advance + 12h warnings, MYS-145/162). On **both staging and
  prod** the deadline job runs every 15 minutes via a systemd timer
  (`mysterymixclub-advance-mixes.timer`) — bootstrap installs and arms it, and
  each deploy refreshes the unit files and re-runs `enable --now`. See
  [`staging-setup.md` §7](staging-setup.md) for the full behavior explanation
  and [`prod-setup.md` §6](prod-setup.md) for what differs on prod (unit files
  sourced from the `-prod`-suffixed scripts, same on-disk unit names).
- **Persistent (`Type=simple`, `Restart=on-failure`, no `.timer`)**:
  `python -m app.jobs.playlist_worker` (MYS-258, ADR 0006) — dequeues the
  Postgres-backed `playlist_jobs` queue (`LISTEN`/`NOTIFY` + `SELECT ... FOR
  UPDATE SKIP LOCKED`) and runs the shared-account Spotify playlist generation
  that used to run inline in the request/deadline-job path. On **both staging
  and prod** it's installed by bootstrap and enabled, and each deploy
  refreshes the unit file and restarts it (a persistent process is
  `restart`ed on deploy, not re-`enable --now`d like a timer). See
  [`staging-setup.md` §7a](staging-setup.md) and
  [`prod-setup.md` §6a](prod-setup.md).

---

## Workflows

| File                              | On                        | Does                                                        |
|-----------------------------------|---------------------------|-------------------------------------------------------------|
| `.github/workflows/ci.yml`        | PR → `main` or `develop`  | Frontend lint/typecheck/test; backend ruff/mypy/pytest+cov  |
| `.github/workflows/deploy-staging.yml` | push → `develop`     | Runs on a self-hosted runner living on the staging Droplet → `scripts/deploy-staging.sh` |
| `.github/workflows/deploy-prod.yml`    | push → `main`        | `build-frontend` job (hosted runner, ungated): builds the SPA, uploads it as an artifact. `deploy` job: `environment: production` approval gate → self-hosted runner on the prod Droplet → downloads the artifact → `scripts/deploy-prod.sh` (MYS-259) |

The `deploy` job in each workflow runs directly on its target Droplet via a
self-hosted GitHub Actions runner (MYS-224/225) — no SSH secrets or
`DIGITALOCEAN_ACCESS_TOKEN` needed for either one. `deploy-prod.yml`'s
`build-frontend` job is the one exception: it deliberately runs on a normal
**hosted** runner (MYS-259) since it never touches the Droplet — building
`npm ci && npm run build` there instead of on the 2 GB prod box removes a real
OOM risk from every prod deploy. See [`staging-setup.md`](staging-setup.md)
and [`prod-setup.md`](prod-setup.md) for runner registration.

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

### App runtime secrets (Droplet env files)

Both environments are self-managed Droplets now, so runtime app config is set
the same way on each — an env file on the box, read by the systemd service,
never in GitHub or DigitalOcean's dashboard:

| Key            | Type     | Notes                                              |
|----------------|----------|-----------------------------------------------------|
| `DATABASE_URL` | SECRET   | points at the box's local Postgres                 |
| `SECRET_KEY`   | SECRET   | JWT signing key — `python -c "import secrets; print(secrets.token_urlsafe(64))"`; never share a value across environments |
| `ENVIRONMENT`  | GENERAL  | `production` / `staging`                           |
| `RESEND_API_KEY`, `ALLOWED_ORIGINS`, `APP_BASE_URL` | SECRET/GENERAL | see `.env.example` |
| `APPLE_MUSIC_TEAM_ID`, `APPLE_MUSIC_KEY_ID`, `APPLE_MUSIC_PRIVATE_KEY` | SECRET | Apple Music (MYS-104/105-108). **All three or none** — any missing and the Apple UI hides itself and links fall back to keyless iTunes. Provisioning walkthrough in `staging-setup.md` → "Enabling Apple Music". |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | SECRET | Google Sign-In (MysteryMixClub-ali8, ADR 0007). **All three or none** — any missing and the Google button hides itself, magic link/password unaffected. Separate OAuth client per environment. Provisioning walkthrough in `staging-setup.md` → "Enabling Google Sign-In". |
| `RESEND_WEBHOOK_SECRET`, `INBOUND_EMAIL_FORWARD_TO` | SECRET/GENERAL | Inbound mail forwarding (MYS-242). Prod-only in practice — Resend Inbound's MX is on the apex domain, which prod serves. Empty `RESEND_WEBHOOK_SECRET` = the webhook route 503s rather than accepting unsigned requests. |

### Adding a new secret (the routine)

**Staging and production now take secrets by the same route** — both are
Droplets (ADR 0002). Doing only one still leaves the other silently
unconfigured, which for optional integrations looks exactly like the feature
"not working" rather than an error, so always do both when a key is
environment-agnostic.

1. Document the key (no value) in `.env.example`.
2. **Staging:** add the key to `scripts/staging.env.example` (no value), then
   set the real value in `/etc/mysterymixclub/staging.env` on the Droplet and
   `sudo systemctl restart mysterymixclub-api`. Settings are cached per
   process, so an edit without the restart changes nothing.
3. **Production:** add the key to `scripts/prod.env.example` (no value), then
   set the real value in `/etc/mysterymixclub/prod.env` on the prod Droplet
   and `sudo systemctl restart mysterymixclub-api`. Same mechanism, different
   box — some keys are environment-specific rather than copy-paste (e.g. a
   redirect URI tied to the domain, or a foreign key into that environment's
   own `users` table); check whether a value is safe to reuse verbatim before
   copying it over.
4. If a *workflow* needs it (not the app at runtime), add it as a GitHub Actions
   secret instead — neither deploy workflow itself needs any secrets today.

> `.do/app.staging.yaml` is **reference only** — staging moved to the Droplet
> (MYS-39) and that spec is not used by the staging deploy. `.do/app.prod.yaml`
> no longer exists at all (deleted after the prod cutover, MYS-225).

---

## Local quickstart

```bash
npm install                      # root: installs husky + commitlint, wires hooks
npm --prefix frontend install    # frontend deps
pip install -e "backend[dev]"    # backend deps (in a venv)
```

Then normal `git commit` / `git push` exercise the hook chain automatically.
