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
3. No domain required for now — staging runs HTTPS on the raw IP with a
   self-signed cert (step 4). Add a domain later to switch to Let's Encrypt
   (step 5).

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
- `VITE_API_BASE_URL` — leave **empty**. The SPA then calls the API same-origin
  (relative `/api/v1/...`), which nginx proxies to the backend. An absolute host
  here (e.g. `http://localhost:8000`) would resolve against the visitor's own
  browser and fail.

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

## 4. TLS cert + Nginx site + basic auth

The site serves HTTPS. With no domain yet, generate a **self-signed** cert (the
Nginx config references `/etc/ssl/mmc-staging/`); testers click through a browser
warning. Then install the site.

```bash
# Self-signed cert for the raw IP (CN defaults to 67.207.81.183).
sudo bash /home/mysterymixclub/app/scripts/generate-self-signed-cert.sh

# Basic-auth file (username mmctest). Choose a password to share with testers.
sudo htpasswd -bc /etc/nginx/.htpasswd-mmc-staging mmctest 'choose-a-test-password'

sudo cp /home/mysterymixclub/app/scripts/nginx-mysterymixclub-staging.conf \
        /etc/nginx/sites-available/mysterymixclub-staging
sudo ln -sf /etc/nginx/sites-available/mysterymixclub-staging \
        /etc/nginx/sites-enabled/mysterymixclub-staging
sudo rm -f /etc/nginx/sites-enabled/default      # drop the default site
sudo nginx -t && sudo systemctl reload nginx
```

Staging is now at `https://<DROPLET_IP>/` behind basic auth (with a cert warning).

> Whenever you edit the site conf afterwards (e.g. to add the HSTS header),
> re-copy it to `/etc/nginx/sites-available/` and apply with
> `sudo nginx -t && sudo systemctl reload nginx`.

> Note: `ENVIRONMENT=staging` means auth cookies are **not** marked `Secure`.
> That's fine here; sign-in still works over the self-signed HTTPS connection.

---

## 5. Later: swap self-signed for a real Let's Encrypt cert

Once a domain (e.g. `staging.mysterymixclub.com`) points at the Droplet:

```bash
# Update server_name in the site file to the domain first, then:
sudo certbot --nginx -d staging.mysterymixclub.com
```

Certbot takes over the `ssl_certificate` directives and installs an auto-renew
timer — no more browser warning. Also update `ALLOWED_ORIGINS` / `APP_BASE_URL`
in `staging.env` to the new domain and restart the service.

---

## 6. Wire up the GitHub Actions deploy

The `Deploy Staging` workflow (`.github/workflows/deploy-staging.yml`) SSHes into
the Droplet on every push to `develop` and runs `scripts/deploy-staging.sh`.

**Sudoers** — the deploy script restarts the service and keeps the deadline-job
units current via sudo (the web root is owned by the deploy user, so the frontend
publish needs no sudo). Grant passwordless sudo for exactly those commands:

```bash
# on the Droplet, as root
cat >/etc/sudoers.d/mysterymixclub-deploy <<'EOF'
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl restart mysterymixclub-api
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/cp /home/mysterymixclub/app/scripts/mysterymixclub-advance-rounds.service /etc/systemd/system/
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/cp /home/mysterymixclub/app/scripts/mysterymixclub-advance-rounds.timer /etc/systemd/system/
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl daemon-reload
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl enable --now mysterymixclub-advance-rounds.timer
EOF
chmod 440 /etc/sudoers.d/mysterymixclub-deploy
```

> The last four lines were added for the MYS-145/162 deadline job. On a Droplet
> bootstrapped before this change, add them to the existing sudoers file (and see
> §7) or the next deploy will fail at the timer-refresh step.

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

## 7. The deadline force-advance job (MYS-145/162)

Rounds close on quorum **or** a deadline, whichever comes first. Quorum is handled
live by the API; the deadline is handled by `app.jobs.advance_rounds`, run on a
15-minute systemd timer. Each run, per live round, it: stamps a missing deadline
from the league window; sends the "about 12 hours left" submit/vote warning once
when the deadline is 1–12h away (only for windows longer than 12h); force-advances
a submission round to voting (or nudges the organizer once if nobody submitted —
that round then waits for a manual advance); and closes a voting round whose
deadline has passed.

**Units** (installed from `scripts/`): `mysterymixclub-advance-rounds.service`
(`Type=oneshot`, same user/env/venv as the API) and
`mysterymixclub-advance-rounds.timer` (`OnCalendar=*:00/15`, `Persistent=true`).
Bootstrap installs and arms them; each deploy refreshes the files and runs
`enable --now`. On a Droplet bootstrapped before this job existed, install once:

```bash
sudo cp /home/mysterymixclub/app/scripts/mysterymixclub-advance-rounds.service /etc/systemd/system/
sudo cp /home/mysterymixclub/app/scripts/mysterymixclub-advance-rounds.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mysterymixclub-advance-rounds.timer
```

**Check it:**

```bash
systemctl list-timers mysterymixclub-advance-rounds.timer   # NEXT / LAST run
sudo journalctl -u mysterymixclub-advance-rounds.service -f # per-run summary line
sudo systemctl start mysterymixclub-advance-rounds.service  # run once, on demand
```

Each run logs a summary: `stamped=… warned=… empty_notices=… advanced=… closed=…
skipped=… errors=…`.

**Disable in an emergency** (stops all deadline-driven transitions; quorum-based
closing keeps working):

```bash
sudo systemctl disable --now mysterymixclub-advance-rounds.timer
```

Re-enable with `sudo systemctl enable --now mysterymixclub-advance-rounds.timer`.

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
- **Deadline job status / logs:** `systemctl list-timers mysterymixclub-advance-rounds.timer`
  and `sudo journalctl -u mysterymixclub-advance-rounds.service -f` (see §7). Rounds
  not advancing at their deadline → check the timer is enabled and the run summary
  for `errors=`.
