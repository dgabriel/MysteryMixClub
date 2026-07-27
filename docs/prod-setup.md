# Production environment — DigitalOcean Droplet

Production runs on a self-managed Ubuntu 24.04 Droplet (IaaS), the same shape
as staging — Nginx serves the frontend build, the FastAPI backend runs under
systemd behind an Nginx reverse proxy, Postgres runs locally on the box — not
DigitalOcean App Platform. See **ADR 0002**
(`docs/adr/0002-prod-platform-self-managed-droplet.md`) for why, and MYS-225
for the tracking ticket.

```
 push to main ─► deploy-prod.yml (self-hosted runner ON the Droplet, no SSH)
                   ├─ build-frontend job (hosted runner): npm ci && npm run build
                   │  → uploads dist/ as a build artifact (MYS-259)
                   └─ deploy job (self-hosted, gated behind `production` approval)
                        ├─ downloads the dist/ artifact → frontend/dist
                        └─ scripts/deploy-prod.sh
                             ├─ git pull main
                             ├─ pip install -e . + alembic upgrade
                             ├─ systemctl reload mysterymixclub-api (graceful; falls
                             │  back to restart only if the service isn't active yet)
                             └─ publish frontend/dist → /var/www/mysterymixclub
```

| Thing            | Value                                            |
|------------------|--------------------------------------------------|
| Service user     | `mysterymixclub`                                 |
| App checkout     | `/home/mysterymixclub/app` (branch `main`)       |
| Backend venv     | `/home/mysterymixclub/app/backend/.venv`         |
| Web root         | `/var/www/mysterymixclub`                        |
| Runtime env file | `/etc/mysterymixclub/prod.env`                   |
| systemd unit     | `mysterymixclub-api` (gunicorn + `uvicorn.workers.UvicornWorker`, 2 workers by default, on `127.0.0.1:8000`; MYS-259) |
| Nginx site       | `/etc/nginx/sites-available/mysterymixclub-prod` |
| Canonical host   | `mysterymixclub.com` (apex — matches technical-design.md §5; `www` 301s to it) |
| Swap             | `/swapfile`, 2G (`bootstrap-droplet-prod.sh`; MYS-259) |

This doc covers the Droplet's OS-level setup. The Droplet, firewall, reserved
IP, and DNS records themselves are provisioned by Terraform —
`infra/terraform/envs/prod/` — see `infra/terraform/README.md` for that layer.
Do the Terraform apply first; this runbook assumes the Droplet already exists.

---

## Prerequisites

1. The prod Droplet applied via `infra/terraform/envs/prod/` (or created by
   hand, if Terraform isn't applied yet) — note its public IP.
2. Your **SSH key** added to the Droplet (you can `ssh root@<ip>`).
3. DNS for `mysterymixclub.com` and `www.mysterymixclub.com` pointed at the
   Droplet's (reserved) IP — needed before running certbot in step 4.
4. Your admin CIDR (e.g. your home/office IP as a `/32`) — used both by the
   Terraform cloud firewall (`ssh_allowed_cidrs` in
   `infra/terraform/envs/prod/terraform.tfvars`) and by this Droplet's own
   `ufw` rule (`ADMIN_SSH_CIDR` below). Production never opens SSH to
   `0.0.0.0/0` — that's the exact anti-pattern flagged on staging (MYS-224).

---

## 1. Bootstrap the Droplet (one time)

```bash
# from your machine
scp -r scripts root@<DROPLET_IP>:/root/

# on the Droplet
PROD_DB_PASSWORD='choose-a-strong-password' \
  ADMIN_SSH_CIDR='203.0.113.4/32' \
  sudo -E bash /root/scripts/bootstrap-droplet-prod.sh
```

This installs packages, provisions a 2G swapfile (`/swapfile`, `vm.swappiness=10`,
MYS-259 — a safety net; this box has no other memory headroom), creates the
`mysterymixclub` user, the `mysterymixclub_prod` Postgres database + `mmc_prod`
role, clones the repo (branch `main`) to `/home/mysterymixclub/app`, builds the
backend venv, and configures `ufw` — port 22 scoped to `ADMIN_SSH_CIDR`, 80/443
open. Idempotent — safe to re-run.

> Optional overrides (env vars): `PROD_DB_NAME`, `PROD_DB_USER`, `REPO_URL`,
> `REPO_BRANCH`, `APP_ROOT`, `WEB_ROOT`, `SWAP_FILE`, `SWAP_SIZE`.

> **This only provisions swap on a fresh droplet.** The bootstrap script never
> re-runs against the *already-live* prod droplet on its own, so if
> `mysterymixclub-prod` was provisioned before MYS-259, it has no swap today
> and applying this requires a one-time manual step on the live box (`fallocate
> -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon
> /swapfile`, plus the matching `/etc/fstab` line and `vm.swappiness=10` in
> `/etc/sysctl.conf` — see the bootstrap script for the exact commands). This
> is **not something Claude can do** (no prod SSH, ever) — it's an operational
> follow-up for Dawn to apply by hand, or to fold into a future full-redeploy
> of the droplet from the updated bootstrap script.

---

## 2. Populate the runtime env file

```bash
sudo cp /home/mysterymixclub/app/scripts/prod.env.example \
        /etc/mysterymixclub/prod.env
sudo nano /etc/mysterymixclub/prod.env
```

Fill in at least:

- `DATABASE_URL` — use the `PROD_DB_PASSWORD` you chose in step 1.
- `SECRET_KEY` — generate a **fresh** value with
  `python3 -c "import secrets; print(secrets.token_urlsafe(64))"`. Never reuse
  staging's key.
- `RESEND_API_KEY` — **required** for prod (unlike staging, there's no
  acceptable "read the link from the journal" fallback for real users).
- `APPLE_MUSIC_TEAM_ID` / `APPLE_MUSIC_KEY_ID` / `APPLE_MUSIC_PRIVATE_KEY` —
  optional, but all three or none. See "Enabling Apple Music" in
  `staging-setup.md` — the process is identical, just against prod's env file.
- `ALLOWED_ORIGINS` / `APP_BASE_URL` — `https://mysterymixclub.com`.
- `GUNICORN_WORKERS` — optional; the systemd unit defaults to `2` (sized for
  this droplet's 2 vCPUs) if left unset. Only set it after resizing the
  droplet or measuring a different optimum, and follow up with a real
  `sudo systemctl restart mysterymixclub-api` (not the deploy script's normal
  `reload`) — see the comment in `scripts/prod.env.example` for why.

Note: `VITE_API_BASE_URL` is **no longer read from this file** (MYS-259) — the
frontend build moved into CI, so this env file is never sourced for it. See
`scripts/prod.env.example`'s comment for where that setting now lives.

Lock it down:

```bash
sudo chmod 640 /etc/mysterymixclub/prod.env
sudo chown root:mysterymixclub /etc/mysterymixclub/prod.env
```

---

## 3. Install the systemd service

```bash
sudo cp /home/mysterymixclub/app/scripts/mysterymixclub-api-prod.service \
        /etc/systemd/system/mysterymixclub-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now mysterymixclub-api
sudo systemctl status mysterymixclub-api      # should be active (running)
```

> **Cutting an already-live droplet over to gunicorn (MYS-259):**
> `scripts/deploy-prod.sh` never re-copies this unit file or runs
> `daemon-reload` on its own — unlike the deadline-job units, this main API
> unit is only ever (re-)installed by this manual step. So merging MYS-259 and
> merely letting the next `main` deploy run is **not enough** to switch the
> live droplet to gunicorn: the already-running bare-`uvicorn` process keeps
> running under the *old* unit definition until someone repeats this step by
> hand.
>
> **What actually happens if you skip this step and deploy anyway:**
> `deploy-prod.sh` attempts `systemctl reload mysterymixclub-api` on every
> deploy. Against the *old* unit (no `ExecReload=` defined at all), that
> reload attempt itself fails — systemd, not the script, rejects it
> ("Job type reload is not applicable"). The script catches that failure and
> falls back to a plain `systemctl restart` of whatever unit is actually
> installed, i.e. the still-old bare-`uvicorn` one. **The deploy still
> succeeds** — new code runs, just still under bare uvicorn, hard-restarted
> — you simply don't get gunicorn/multiple workers/graceful reload until the
> manual cutover below happens. (An earlier version of this script instead
> pre-decided reload-vs-restart from `systemctl is-active`, which does NOT
> distinguish "not active yet" from "active but missing ExecReload=" — that
> version would have let the reload attempt hard-fail mid-script, aborting the
> deploy job **after** the alembic migration above had already run against
> prod. Fixed before merge; flagging here so the failure mode is understood,
> not just the current safe behavior.)
>
> To actually cut over: repeat the `cp` + `daemon-reload` above, then finish
> with a real `sudo systemctl restart mysterymixclub-api` (not `reload` — the
> running process needs to actually re-exec under the new `ExecStart` to
> become gunicorn at all; `reload`/SIGHUP only does something useful once
> gunicorn is already the thing running). This is a one-time, deliberate
> cutover step for Dawn — not something Claude does (no prod SSH). After that
> one restart, routine deploys use the normal graceful `reload` from step 5
> onward, and the fallback above stops being exercised.

Apply the first migration and confirm the API answers locally:

```bash
sudo -u mysterymixclub bash -c '
  cd /home/mysterymixclub/app/backend &&
  set -a && source /etc/mysterymixclub/prod.env && set +a &&
  .venv/bin/alembic upgrade head'
curl -s http://127.0.0.1:8000/api/v1/healthz   # -> {"status":"ok"}
```

---

## 4. Nginx site + Let's Encrypt cert

Unlike staging, the domain is already known — skip the self-signed step
entirely and go straight to a real cert. There is no basic auth: these are
real users, and Basic auth would collide with the API's own
`Authorization: Bearer` header (see the comment in the nginx conf).

```bash
sudo cp /home/mysterymixclub/app/scripts/nginx-mysterymixclub-prod.conf \
        /etc/nginx/sites-available/mysterymixclub-prod
sudo ln -sf /etc/nginx/sites-available/mysterymixclub-prod \
        /etc/nginx/sites-enabled/mysterymixclub-prod
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# Only once DNS for both names actually resolves to this Droplet:
sudo certbot --nginx -d mysterymixclub.com -d www.mysterymixclub.com
```

Certbot rewrites the `ssl_certificate` directives and installs an auto-renew
timer.

---

## 5. Wire up the GitHub Actions deploy

The `Deploy Production` workflow (`.github/workflows/deploy-prod.yml`) has two
jobs (MYS-259):

1. `build-frontend` — a normal **hosted** GitHub Actions runner (`ubuntu-latest`),
   ungated. Builds the SPA (`npm ci && npm run build`) and uploads `dist/` as a
   build artifact. Runs on every push to `main`, including before approval, since
   it never touches the Droplet.
2. `deploy` — the **self-hosted GitHub Actions runner living on the Droplet
   itself** — gated behind the `production` GitHub environment's
   required-reviewer approval. Downloads the `build-frontend` job's artifact
   into `frontend/dist`, then runs `scripts/deploy-prod.sh`, which publishes
   that already-built bundle (it no longer builds anything itself).

If the SPA ever needs to call an API on a different host than itself, set a
`VITE_API_BASE_URL` **repository-level** Actions variable (Settings → Secrets
and variables → Actions → Variables tab — NOT a secret, it ends up in the
public JS bundle either way, and NOT the `production` environment's
Variables). It must be repo-level: `build-frontend` (the job that consumes
it) has no `environment:` key — it never touches the Droplet, so it isn't
gated — and GitHub only exposes environment-scoped variables to jobs that
declare that same environment. An environment-scoped variable here would be
silently invisible to `build-frontend`. Unset defaults to empty, i.e.
same-origin, which is correct today.

**Why self-hosted, not SSH-in like staging:** the prod cloud firewall (and
this Droplet's host `ufw`) restrict inbound SSH to a single admin CIDR (fixing
the anti-pattern flagged on staging, MYS-224) — from day one, not after the
fact. GitHub-hosted runners connect from constantly-changing IP ranges too
broad and volatile to safely allowlist, so `appleboy/ssh-action` (staging's
approach) can never reach this box. A self-hosted runner sidesteps the problem
entirely: it long-polls GitHub over an outbound connection, so no inbound
firewall rule is needed at all.

**Sudoers** — the deploy script attempts a graceful reload of the service and
falls back to a real restart if that reload itself fails (not active yet, or
the live unit predates `ExecReload=` — see `scripts/deploy-prod.sh`), and
keeps the deadline-job units current via sudo (the web root is owned by the
deploy user, so the frontend publish needs no sudo). Both `reload` and
`restart` need a grant since either may run on any given deploy:

```bash
# on the Droplet, as root
cat >/etc/sudoers.d/mysterymixclub-deploy <<'EOF'
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl reload mysterymixclub-api
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl restart mysterymixclub-api
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/cp /home/mysterymixclub/app/scripts/mysterymixclub-advance-mixes-prod.service /etc/systemd/system/mysterymixclub-advance-mixes.service
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/cp /home/mysterymixclub/app/scripts/mysterymixclub-advance-mixes-prod.timer /etc/systemd/system/mysterymixclub-advance-mixes.timer
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/cp /home/mysterymixclub/app/scripts/mysterymixclub-playlist-worker-prod.service /etc/systemd/system/mysterymixclub-playlist-worker.service
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl daemon-reload
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl enable --now mysterymixclub-advance-mixes.timer
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl enable mysterymixclub-playlist-worker
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl restart mysterymixclub-playlist-worker
EOF
chmod 440 /etc/sudoers.d/mysterymixclub-deploy
```

> If this sudoers file was set up **before** MYS-259, add the
> `systemctl reload mysterymixclub-api` line to the existing
> `/etc/sudoers.d/mysterymixclub-deploy` by hand (`restart` was already
> granted, so the fallback path already works — only `reload`, the new normal
> path, needs adding). This is a one-time manual edit on the live Droplet;
> Dawn should apply it, not Claude (no prod SSH).
>
> The three `playlist-worker` lines were added for MYS-258 (ADR 0006). On a
> Droplet bootstrapped before this change, add them by hand too, or the next
> deploy fails at the worker-refresh step — same "Dawn applies it, not Claude"
> rule as above.

**Register the runner** (as the `mysterymixclub` user — reuses the sudoers
grant above, matches the app's own file ownership):

```bash
# Get a registration token (needs repo-admin access; expires in ~1h):
gh api -X POST repos/dgabriel/MysteryMixClub/actions/runners/registration-token --jq .token

# On the Droplet, as mysterymixclub:
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v<VERSION>/actions-runner-linux-x64-<VERSION>.tar.gz
tar xzf actions-runner-linux-x64.tar.gz && rm actions-runner-linux-x64.tar.gz
./config.sh --url https://github.com/dgabriel/MysteryMixClub --token <TOKEN> \
  --name mysterymixclub-prod --labels prod --work _work --unattended --replace

# As root, install + start it as a systemd service running under mysterymixclub:
cd /home/mysterymixclub/actions-runner
./svc.sh install mysterymixclub
./svc.sh start
```

Confirm it's online: `gh api repos/dgabriel/MysteryMixClub/actions/runners --jq '.runners[] | {name, status}'`.
The workflow targets it via `runs-on: [self-hosted, prod]` — the `prod` label
is what scopes deploy jobs to this specific runner (relevant once/if staging
ever gets its own self-hosted runner too).

**No SSH secrets needed** — `PROD_HOST`/`PROD_SSH_USER`/`PROD_SSH_KEY` were
used by the old SSH-based workflow and are no longer referenced. Safe to
delete from the `production` environment's secrets, or just leave them unused.

**If the Droplet is ever rebuilt**, the runner registration is lost with it —
re-run the registration steps above on the new box before the first deploy.

Then push to `main` (or re-run the workflow) to trigger a deploy. Remember:
per `docs/git-hygiene.md`, `main` only receives deliberate promotion PRs from
`develop` — this workflow won't fire until that promotion actually happens.

---

## 6. The deadline force-advance job (MYS-145/162)

Same job as staging — see `staging-setup.md` §7 for the full behavior
explanation. On prod the units are named identically on-disk
(`mysterymixclub-advance-mixes.service`/`.timer`) but sourced from the
`-prod`-suffixed repo files. Bootstrap installs and arms them; each deploy
refreshes the files and runs `enable --now`.

```bash
systemctl list-timers mysterymixclub-advance-mixes.timer   # NEXT / LAST run
sudo journalctl -u mysterymixclub-advance-mixes.service -f # per-run summary line
```

---

## 6a. The playlist-generation worker (MYS-258, ADR 0006)

Same worker as staging — see `staging-setup.md` §7a for the full behavior
explanation. On prod the unit is named identically on-disk
(`mysterymixclub-playlist-worker.service`) but sourced from the
`-prod`-suffixed repo file. Bootstrap installs and enables it; each deploy
refreshes the unit file and restarts it.

```bash
systemctl status mysterymixclub-playlist-worker
sudo journalctl -u mysterymixclub-playlist-worker -f
```

---

## What changes vs. staging (deliberately, not by oversight)

- **No basic auth.** Real users need direct access; see the nginx conf comment
  for why Basic auth would also break the API's Bearer-token auth.
- **Real cert from the start**, not self-signed — the domain is known before
  the Droplet exists, so there's no bare-IP bootstrap period to cover.
- **SSH restricted at both layers** — the Terraform cloud firewall AND this
  Droplet's own `ufw` scope port 22 to `ADMIN_SSH_CIDR`, never `0.0.0.0/0`.
- **Separate secrets, separate keys.** `SECRET_KEY`, the DB password, and the
  SSH deploy keypair are all distinct from staging's — nothing shared across
  environments.
- **Gunicorn + multiple workers, not bare uvicorn** (MYS-259). Staging's
  `mysterymixclub-api.service` still runs a single bare `uvicorn` process —
  prod runs `gunicorn` with `uvicorn.workers.UvicornWorker`, sized to this
  droplet's 2 vCPUs (`GUNICORN_WORKERS=2` by default). Staging's `s-1vcpu-1gb`
  box gets little from multiple workers on 1 vCPU; revisit if staging traffic
  ever justifies it.
- **Graceful `reload` on deploy, not a hard `restart`** (MYS-259) — SIGHUP
  tells gunicorn to spin up new workers on the new code and drain the old ones
  before killing them, so in-flight requests survive a deploy. Staging still
  does a hard `restart` (bare uvicorn has nothing to gracefully reload without
  its own process manager).
- **Frontend built in CI, not on the Droplet** (MYS-259) — a hosted GitHub
  Actions runner builds the SPA and hands the built `dist/` to the deploy job
  as an artifact. Staging still runs `npm ci && npm run build` on its own box;
  its `s-1vcpu-1gb` droplet is more exposed to this (less RAM than prod had
  before this change), so this is a candidate follow-up for staging too — not
  done here to keep this change scoped to prod (see the Linear ticket note in
  this doc's history / MYS-259 comments).
- **Swap provisioned at bootstrap** (MYS-259) — a 2G swapfile as an OOM safety
  net. Staging has none today; lower stakes on a non-production environment,
  and not required by this ticket's scope.

---

## Troubleshooting

Same failure modes and commands as staging (`staging-setup.md`
"Troubleshooting"), pointed at prod's unit names and env file:
`sudo systemctl status mysterymixclub-api`,
`sudo journalctl -u mysterymixclub-api -f`, and
`sudo -u mysterymixclub /home/mysterymixclub/app/scripts/deploy-prod.sh` for a
manual deploy.

## If this Droplet is ever compromised

This is where real production user data lives — see
`docs/security/breach-notification-runbook.md` for containment, scoping, and
the GDPR 72-hour notification process (MYS-187).
