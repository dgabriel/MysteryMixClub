# Staging environment — DigitalOcean Droplet

Staging runs on a single **$6/mo Ubuntu 24.04 Droplet** (IaaS), not DigitalOcean
App Platform. The frontend build is served by Nginx; the FastAPI backend runs
under systemd behind an Nginx reverse proxy; Postgres runs locally on the box.
Production still deploys via App Platform — see [`ci-cd.md`](ci-cd.md).

```
 push to develop ─► deploy-staging.yml ─► ssh ─► scripts/deploy-staging.sh
                                                  ├─ git pull develop
                                                  ├─ pip install -e . + alembic upgrade
                                                  ├─ systemctl restart mysterymixclub-api
                                                  └─ npm ci && npm run build → /var/www/mysterymixclub
```

| Thing            | Value                                            |
|------------------|--------------------------------------------------|
| Service user     | `mysterymixclub`                                 |
| App checkout     | `/home/mysterymixclub/app` (branch `develop`)    |
| Backend venv     | `/home/mysterymixclub/app/backend/.venv`         |
| Web root         | `/var/www/mysterymixclub`                        |
| Runtime env file | `/etc/mysterymixclub/staging.env`                |
| systemd unit     | `mysterymixclub-api` (uvicorn on `127.0.0.1:8000`) |
| Nginx site       | `/etc/nginx/sites-available/mysterymixclub-staging` |
| Basic-auth file  | `/etc/nginx/.htpasswd-mmc-staging` (user `mmctest`) |

---

## Prerequisites

1. A **$6/mo Ubuntu 24.04 Droplet** created in DigitalOcean; note its public IP.
2. Your **SSH key** added to the Droplet (you can `ssh root@<ip>`).
3. Either a DNS record (e.g. `staging.mysterymixclub.com` → Droplet IP) **or**
   plan to use the raw IP over HTTP for now (skip Certbot).

---

## 1. Bootstrap the Droplet (one time)

Copy the repo's `scripts/` to the box (or clone it) and run the bootstrap as
root, passing the staging DB password in the environment:

```bash
# from your machine
scp -r scripts root@<DROPLET_IP>:/root/

# on the Droplet
STAGING_DB_PASSWORD='choose-a-strong-password' \
  sudo -E bash /root/scripts/bootstrap-droplet.sh
```

This installs packages, creates the `mysterymixclub` user, the `mysterymixclub_staging`
Postgres database + `mmc_staging` role, clones the repo to
`/home/mysterymixclub/app`, builds the backend venv, and opens ports 22/80/443.
It is idempotent — safe to re-run.

> Optional overrides (env vars): `STAGING_DB_NAME`, `STAGING_DB_USER`,
> `REPO_URL`, `REPO_BRANCH`, `APP_ROOT`, `WEB_ROOT`.

---

## 2. Populate the runtime env file

```bash
sudo cp /home/mysterymixclub/app/scripts/staging.env.example \
        /etc/mysterymixclub/staging.env
sudo nano /etc/mysterymixclub/staging.env
```

Fill in at least:

- `DATABASE_URL` — use the `STAGING_DB_PASSWORD` you chose in step 1, e.g.
  `postgresql+asyncpg://mmc_staging:<password>@localhost:5432/mysterymixclub_staging`
- `SECRET_KEY` — generate with
  `python3 -c "import secrets; print(secrets.token_urlsafe(64))"`
- `RESEND_API_KEY` — set this so magic-link emails are actually sent. If left
  empty, links are only written to the service journal (see Troubleshooting).
- `ALLOWED_ORIGINS` / `APP_BASE_URL` — your staging URL.

Lock it down:

```bash
sudo chmod 640 /etc/mysterymixclub/staging.env
sudo chown root:mysterymixclub /etc/mysterymixclub/staging.env
```

---

## 3. Install the systemd service

```bash
sudo cp /home/mysterymixclub/app/scripts/mysterymixclub-api.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mysterymixclub-api
sudo systemctl status mysterymixclub-api      # should be active (running)
```

Apply the first migration and confirm the API answers locally:

```bash
sudo -u mysterymixclub bash -c '
  cd /home/mysterymixclub/app/backend &&
  set -a && source /etc/mysterymixclub/staging.env && set +a &&
  .venv/bin/alembic upgrade head'
curl -s http://127.0.0.1:8000/api/v1/healthz   # -> {"status":"ok"}
```

---

## 4. Install the Nginx site + basic auth

```bash
# Basic-auth file (username mmctest). Choose a password to share with testers.
sudo htpasswd -bc /etc/nginx/.htpasswd-mmc-staging mmctest 'choose-a-test-password'

sudo cp /home/mysterymixclub/app/scripts/nginx-mysterymixclub-staging.conf \
        /etc/nginx/sites-available/mysterymixclub-staging
sudo ln -sf /etc/nginx/sites-available/mysterymixclub-staging \
        /etc/nginx/sites-enabled/mysterymixclub-staging
sudo rm -f /etc/nginx/sites-enabled/default      # drop the default site
sudo nginx -t && sudo systemctl reload nginx
```

Edit `server_name` in the site file to match your domain (or set it to `_` if
using the raw IP).

---

## 5. SSL with Certbot (or skip for now)

**With a domain:**

```bash
sudo certbot --nginx -d staging.mysterymixclub.com
```

Certbot rewrites the site file to add the HTTPS server block and an HTTP→HTTPS
redirect, and installs an auto-renew timer.

**Without a domain (raw IP, HTTP only):** skip Certbot. The site is reachable at
`http://<DROPLET_IP>/` behind basic auth. Note browsers will treat it as
insecure and `ENVIRONMENT=staging` means auth cookies are not marked `Secure`,
which is fine over plain HTTP.

---

## 6. Wire up the GitHub Actions deploy

The `Deploy Staging` workflow (`.github/workflows/deploy-staging.yml`) SSHes into
the Droplet on every push to `develop` and runs `scripts/deploy-staging.sh`.

**Sudoers** — the SSH user runs `systemctl restart` and `cp` to the web root via
sudo. Grant passwordless sudo for just those commands:

```bash
# on the Droplet, as root
cat >/etc/sudoers.d/mysterymixclub-deploy <<'EOF'
mysterymixclub ALL=(root) NOPASSWD: /bin/systemctl restart mysterymixclub-api, /bin/cp -r /home/mysterymixclub/app/frontend/dist/* /var/www/mysterymixclub/
EOF
chmod 440 /etc/sudoers.d/mysterymixclub-deploy
```

**GitHub secrets** (Settings → Secrets and variables → Actions → environment
`staging`):

| Secret            | Value                                                        |
|-------------------|-------------------------------------------------------------|
| `STAGING_HOST`    | Droplet public IP or hostname                               |
| `STAGING_SSH_USER`| `mysterymixclub`                                            |
| `STAGING_SSH_KEY` | a **private** key whose public half is in `mysterymixclub`'s `~/.ssh/authorized_keys` |

Create a deploy key on the Droplet and authorize it:

```bash
sudo -u mysterymixclub ssh-keygen -t ed25519 -f /home/mysterymixclub/.ssh/deploy -N ''
sudo -u mysterymixclub bash -c 'cat /home/mysterymixclub/.ssh/deploy.pub >> /home/mysterymixclub/.ssh/authorized_keys'
sudo cat /home/mysterymixclub/.ssh/deploy   # paste this private key into STAGING_SSH_KEY
```

Then push to `develop` (or re-run the workflow) to trigger a deploy.

---

## What to share with the test team

- **URL:** `https://staging.mysterymixclub.com` (or `http://<DROPLET_IP>/`)
- **Basic auth:** username `mmctest`, password (the one set in step 4)
- Sign-in is magic-link based; with `RESEND_API_KEY` set, testers receive the
  link by email.

---

## Troubleshooting

- **API status / logs:** `sudo systemctl status mysterymixclub-api` and
  `sudo journalctl -u mysterymixclub-api -f`.
- **Magic link not emailed:** if `RESEND_API_KEY` is empty the app falls back to
  the console sender; the link is logged — `sudo journalctl -u mysterymixclub-api | grep -i "magic link"`.
- **502 from Nginx:** the API isn't listening on `127.0.0.1:8000` — check the
  service and that `staging.env` is valid (a bad value makes the app exit on boot).
- **Manual deploy:** `sudo -u mysterymixclub /home/mysterymixclub/app/scripts/deploy-staging.sh`.
