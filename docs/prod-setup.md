# Production environment — DigitalOcean Droplet

Production runs on a self-managed Ubuntu 24.04 Droplet (IaaS), the same shape
as staging — Nginx serves the frontend build, the FastAPI backend runs under
systemd behind an Nginx reverse proxy, Postgres runs locally on the box — not
DigitalOcean App Platform. See **ADR 0002**
(`docs/adr/0002-prod-platform-self-managed-droplet.md`) for why, and MYS-225
for the tracking ticket.

```
 push to main ─► deploy-prod.yml ─► ssh ─► scripts/deploy-prod.sh
                                            ├─ git pull main
                                            ├─ pip install -e . + alembic upgrade
                                            ├─ systemctl restart mysterymixclub-api
                                            └─ npm ci && npm run build → /var/www/mysterymixclub
```

| Thing            | Value                                            |
|------------------|--------------------------------------------------|
| Service user     | `mysterymixclub`                                 |
| App checkout     | `/home/mysterymixclub/app` (branch `main`)       |
| Backend venv     | `/home/mysterymixclub/app/backend/.venv`         |
| Web root         | `/var/www/mysterymixclub`                        |
| Runtime env file | `/etc/mysterymixclub/prod.env`                   |
| systemd unit     | `mysterymixclub-api` (uvicorn on `127.0.0.1:8000`) |
| Nginx site       | `/etc/nginx/sites-available/mysterymixclub-prod` |
| Canonical host   | `www.mysterymixclub.com` (apex 301s to it — MYS-174) |

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

This installs packages, creates the `mysterymixclub` user, the
`mysterymixclub_prod` Postgres database + `mmc_prod` role, clones the repo
(branch `main`) to `/home/mysterymixclub/app`, builds the backend venv, and
configures `ufw` — port 22 scoped to `ADMIN_SSH_CIDR`, 80/443 open. Idempotent
— safe to re-run.

> Optional overrides (env vars): `PROD_DB_NAME`, `PROD_DB_USER`, `REPO_URL`,
> `REPO_BRANCH`, `APP_ROOT`, `WEB_ROOT`.

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
- `ALLOWED_ORIGINS` / `APP_BASE_URL` — `https://www.mysterymixclub.com`.
- `VITE_API_BASE_URL` — leave **empty** (same-origin, as staging).

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
sudo certbot --nginx -d www.mysterymixclub.com -d mysterymixclub.com
```

Certbot rewrites the `ssl_certificate` directives and installs an auto-renew
timer.

---

## 5. Wire up the GitHub Actions deploy

The `Deploy Production` workflow (`.github/workflows/deploy-prod.yml`) SSHes
into the Droplet on every push to `main` — gated behind the `production`
GitHub environment's required-reviewer approval — and runs
`scripts/deploy-prod.sh`.

**Sudoers** — the deploy script restarts the service and keeps the
deadline-job units current via sudo (the web root is owned by the deploy user,
so the frontend publish needs no sudo):

```bash
# on the Droplet, as root
cat >/etc/sudoers.d/mysterymixclub-deploy <<'EOF'
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl restart mysterymixclub-api
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/cp /home/mysterymixclub/app/scripts/mysterymixclub-advance-mixes-prod.service /etc/systemd/system/mysterymixclub-advance-mixes.service
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/cp /home/mysterymixclub/app/scripts/mysterymixclub-advance-mixes-prod.timer /etc/systemd/system/mysterymixclub-advance-mixes.timer
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl daemon-reload
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl enable --now mysterymixclub-advance-mixes.timer
EOF
chmod 440 /etc/sudoers.d/mysterymixclub-deploy
```

**GitHub secrets** (Settings → Secrets and variables → Actions → environment
`production`):

| Secret          | Value                                                        |
|-----------------|---------------------------------------------------------------|
| `PROD_HOST`     | Droplet public (reserved) IP or hostname                     |
| `PROD_SSH_USER` | `mysterymixclub`                                              |
| `PROD_SSH_KEY`  | a **private** key whose public half is in `mysterymixclub`'s `~/.ssh/authorized_keys` |

Create a deploy key on the Droplet and authorize it:

```bash
sudo -u mysterymixclub ssh-keygen -t ed25519 -f /home/mysterymixclub/.ssh/deploy -N ''
sudo -u mysterymixclub bash -c 'cat /home/mysterymixclub/.ssh/deploy.pub >> /home/mysterymixclub/.ssh/authorized_keys'
sudo cat /home/mysterymixclub/.ssh/deploy   # paste this private key into PROD_SSH_KEY
```

Use a **different** deploy keypair than staging's — don't reuse the same
private key across environments.

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
