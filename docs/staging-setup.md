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

The bootstrap also creates a 2GB swap file if the Droplet has none. This
$6/mo box only has ~1GB RAM, and `npm ci` for the frontend has been observed
to get OOM-killed outright without swap (`MysteryMixClub-jrm2`,
2026-09-15) -- which aborts `deploy-staging.sh` mid-way through publishing
the frontend, since `set -euo pipefail` means the failed `npm ci` takes the
whole deploy down with it. Check `free -h` after bootstrapping a new Droplet
if you ever see a deploy fail with `npm ci ... Killed`.

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
- `APPLE_MUSIC_TEAM_ID` / `APPLE_MUSIC_KEY_ID` / `APPLE_MUSIC_PRIVATE_KEY` —
  optional, but **all three or none**: with any unset the Apple Music UI renders
  nothing and Apple links fall back to the keyless iTunes lookup. The private key
  must be a single line here, quoted, with literal `\n` between PEM lines. See
  "Enabling Apple Music" below.
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
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl disable --now mysterymixclub-advance-rounds.timer
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/rm -f /etc/systemd/system/mysterymixclub-advance-rounds.service /etc/systemd/system/mysterymixclub-advance-rounds.timer
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/cp /home/mysterymixclub/app/scripts/mysterymixclub-advance-mixes.service /etc/systemd/system/
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/cp /home/mysterymixclub/app/scripts/mysterymixclub-advance-mixes.timer /etc/systemd/system/
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/cp /home/mysterymixclub/app/scripts/mysterymixclub-playlist-worker.service /etc/systemd/system/
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/cp /home/mysterymixclub/app/scripts/mysterymixclub-expire-youtube-ids.service /etc/systemd/system/
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/cp /home/mysterymixclub/app/scripts/mysterymixclub-expire-youtube-ids.timer /etc/systemd/system/
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl daemon-reload
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl enable --now mysterymixclub-advance-mixes.timer
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl enable --now mysterymixclub-expire-youtube-ids.timer
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl enable mysterymixclub-playlist-worker
mysterymixclub ALL=(root) NOPASSWD: /usr/bin/systemctl restart mysterymixclub-playlist-worker
EOF
chmod 440 /etc/sudoers.d/mysterymixclub-deploy
```

> The four `advance-mixes` lines were added for the MYS-145/162 deadline job. On
> a Droplet bootstrapped before this change, add them to the existing sudoers
> file (and see §7) or the next deploy will fail at the timer-refresh step.
>
> The `disable --now .../rm -f ...advance-rounds...` lines were added for
> MYS-195 (the club/mix identifier rename), which deletes `advance_rounds.py`
> — the old unit's `ExecStart` target. `deploy-staging.sh` guards both commands
> with `|| true` so a Droplet without this grant yet won't fail its deploy, but
> the old unit will linger and start erroring in journalctl every time it fires
> (its target module is gone) until this grant is applied by hand on the
> **live staging Droplet** — do this before or at the next deploy off `develop`.
>
> The three `playlist-worker` lines were added for MYS-258 (ADR 0006, the
> Postgres-backed playlist job queue) — see §7a. On a Droplet bootstrapped
> before this change, add them to the existing sudoers file or the next deploy
> will fail at the worker-refresh step.
>
> The three `expire-youtube-ids` lines were added for MysteryMixClub-7a7x
> (ADR 0016, the 30-day YouTube id retention sweep) — see §7b. These are
> **optional**: the deploy guards those steps with `|| true`
> (MysteryMixClub-l4cv), so a Droplet without the grants deploys cleanly and
> simply leaves the sweep un-armed. Add them when you intend to turn the sweep
> on; confirm with
> `systemctl list-timers mysterymixclub-expire-youtube-ids.timer`.

**Deploy via a self-hosted GitHub Actions runner living on the Droplet itself**
(added MYS-224, replacing the `appleboy/ssh-action` approach below it used to
use). Once MYS-224 restricted the cloud firewall's inbound SSH to a single
admin CIDR, a GitHub-hosted runner's constantly-changing IP could no longer
reach this box at all — the same tradeoff prod already made (see
`docs/prod-setup.md` §5), just applied to staging a little after the fact.
A self-hosted runner long-polls GitHub over an outbound connection, so no
inbound firewall rule is needed:

```bash
# Get a registration token (needs repo-admin access; expires in ~1h):
gh api -X POST repos/dgabriel/MysteryMixClub/actions/runners/registration-token --jq .token

# On the Droplet, as mysterymixclub (reuses this user's existing sudoers
# grant above, matches the app's own file ownership):
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v<VERSION>/actions-runner-linux-x64-<VERSION>.tar.gz
tar xzf actions-runner-linux-x64.tar.gz && rm actions-runner-linux-x64.tar.gz
./config.sh --url https://github.com/dgabriel/MysteryMixClub --token <TOKEN> \
  --name mysterymixclub-staging --labels staging --work _work --unattended --replace

# As root, install + start it as a systemd service running under mysterymixclub:
cd /home/mysterymixclub/actions-runner
./svc.sh install mysterymixclub
./svc.sh start
```

Confirm it's online: `gh api repos/dgabriel/MysteryMixClub/actions/runners --jq '.runners[] | {name, status}'`.
The workflow targets it via `runs-on: [self-hosted, staging]` — the `staging`
label is what scopes deploy jobs to this specific runner, separate from
prod's `prod`-labeled one.

**Make the runner service auto-restart (`MysteryMixClub-jrm2`, 2026-09-15).**
`./svc.sh install` generates a unit with no `Restart=` directive, so a runner
process killed by anything (the OOM kill this bead traces, a bad deploy step,
a Droplet hiccup) stays dead until someone notices and restarts it by hand --
which is exactly what happened here: the runner sat crashed for 7 hours,
silently queuing every deploy with nothing to pick them up. Add a drop-in
rather than editing the generated unit file directly (`svc.sh` may
regenerate it):

```bash
sudo mkdir -p /etc/systemd/system/actions.runner.dgabriel-MysteryMixClub.mysterymixclub-staging.service.d
sudo tee /etc/systemd/system/actions.runner.dgabriel-MysteryMixClub.mysterymixclub-staging.service.d/override.conf <<'EOF'
[Service]
Restart=on-failure
RestartSec=10
EOF
sudo systemctl daemon-reload
```

Do this once per runner install (it doesn't survive `svc.sh uninstall` +
reinstall). Verify with
`systemctl show actions.runner.<name>.service -p Restart`.

**No SSH secrets needed** — `STAGING_HOST`/`STAGING_SSH_USER`/`STAGING_SSH_KEY`
were used by the old SSH-based workflow and are no longer referenced. Safe to
delete from the `staging` environment's secrets, or just leave them unused.

**If the Droplet is ever rebuilt**, the runner registration is lost with it —
re-run the registration steps above on the new box before the first deploy.

Then push to `develop` (or re-run the workflow) to trigger a deploy.

---

## 7. The deadline force-advance job (MYS-145/162)

Mystery mixes close on quorum **or** a deadline, whichever comes first. Quorum is
handled live by the API; the deadline is handled by `app.jobs.advance_mixes`, run
on a 15-minute systemd timer. Each run, per live mix, it: stamps a missing
deadline from the club window; sends the "about 12 hours left" submit/vote
warning once when the deadline is 1–12h away (only for windows longer than 12h);
force-advances a submission mix to voting (or nudges the organizer once if
nobody submitted — that mix then waits for a manual advance); and closes a
voting mix whose deadline has passed.

**Units** (installed from `scripts/`): `mysterymixclub-advance-mixes.service`
(`Type=oneshot`, same user/env/venv as the API) and
`mysterymixclub-advance-mixes.timer` (`OnCalendar=*:00/15`, `Persistent=true`).
Bootstrap installs and arms them; each deploy refreshes the files and runs
`enable --now`. On a Droplet bootstrapped before this job existed, install once:

```bash
sudo cp /home/mysterymixclub/app/scripts/mysterymixclub-advance-mixes.service /etc/systemd/system/
sudo cp /home/mysterymixclub/app/scripts/mysterymixclub-advance-mixes.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mysterymixclub-advance-mixes.timer
```

**Check it:**

```bash
systemctl list-timers mysterymixclub-advance-mixes.timer   # NEXT / LAST run
sudo journalctl -u mysterymixclub-advance-mixes.service -f # per-run summary line
sudo systemctl start mysterymixclub-advance-mixes.service  # run once, on demand
```

Each run logs a summary: `stamped=… warned=… empty_notices=… advanced=… closed=…
skipped=… errors=…`.

**Disable in an emergency** (stops all deadline-driven transitions; quorum-based
closing keeps working):

```bash
sudo systemctl disable --now mysterymixclub-advance-mixes.timer
```

Re-enable with `sudo systemctl enable --now mysterymixclub-advance-mixes.timer`.

---

## YouTube id retention sweep (MysteryMixClub-7a7x, ADR 0016)

**This one is a compliance control, not a feature.** YouTube API Services
Developer Policies III.E.4(d) caps storage of Non-Authorized Data at 30 calendar
days, and `submissions.youtube_video_id` is exactly that. The sweep clears every
id past the window and rewrites its exact `watch?v=` links in `platform_links`
back to search deep links.

> **Currently dark.** The job is gated on `YOUTUBE_RETENTION_SWEEP_ENABLED`
> (default `false`), so an armed timer exits immediately without touching a row.
> The deploy installs the units best-effort (`|| true`) and cannot fail on them.
> **Nothing is enforced until the flag is set** — see `docs/feature-flags.md`
> for the rollout steps.

**Units** (installed from `scripts/`): `mysterymixclub-expire-youtube-ids.service`
(`Type=oneshot`, same user/env/venv as the API) and
`mysterymixclub-expire-youtube-ids.timer` (`OnCalendar=daily`,
`Persistent=true` so a missed run fires on next boot rather than being skipped).

```bash
sudo cp /home/mysterymixclub/app/scripts/mysterymixclub-expire-youtube-ids.service /etc/systemd/system/
sudo cp /home/mysterymixclub/app/scripts/mysterymixclub-expire-youtube-ids.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mysterymixclub-expire-youtube-ids.timer
```

**Check it:**

```bash
systemctl list-timers mysterymixclub-expire-youtube-ids.timer
sudo journalctl -u mysterymixclub-expire-youtube-ids.service -f
sudo systemctl start mysterymixclub-expire-youtube-ids.service  # run once, on demand
```

Each run logs `expired N cached YouTube video id(s) past 30 days`. The sweep is
idempotent, so an extra run is a no-op.

**Do not disable this to save quota.** Expired ids re-resolve only when someone
actually opens the mix, so the ongoing cost is already proportional to use. If
quota pressure is the problem, the lever is the audit (see ADR 0016), not the
retention window.

---

## 7a. The playlist-generation worker (MYS-258, ADR 0006)

Playlist generation (the shared-account Spotify playlist, auto-triggered when
a mix opens for voting) no longer runs inline in the request/deadline-job
path — `PATCH /mixes/{id}` and `app.jobs.advance_mixes` only enqueue a
`playlist_jobs` row (`app.services.playlist_jobs.enqueue_playlist_job`) and
`NOTIFY` a Postgres channel; this worker (`app.jobs.playlist_worker`) does the
actual generation. Unlike the deadline job above, it's a **persistent
process**, not timer-triggered: it `LISTEN`s on the `playlist_jobs` channel
for near-instant dispatch, with a 30s poll fallback in case a `NOTIFY` is ever
missed (a dropped/reconnecting listener isn't guaranteed delivery), and
dequeues via `SELECT ... FOR UPDATE SKIP LOCKED`.

**Unit** (installed from `scripts/`): `mysterymixclub-playlist-worker.service`
(`Type=simple`, `Restart=on-failure`, same user/env/venv as the API) — no
paired `.timer`. Bootstrap installs and enables it; each deploy refreshes the
unit file and restarts it (a plain `restart`, not `enable --now`, since it's
already enabled from bootstrap — this is what both picks up new code on every
deploy and starts it for the first time after a fresh bootstrap). On a
Droplet bootstrapped before this job existed, install once:

```bash
sudo cp /home/mysterymixclub/app/scripts/mysterymixclub-playlist-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mysterymixclub-playlist-worker
```

**Check it:**

```bash
systemctl status mysterymixclub-playlist-worker            # running? since when?
sudo journalctl -u mysterymixclub-playlist-worker -f        # live log — listens on startup, logs each drained batch
```

It logs `playlist_worker: listening on 'playlist_jobs' (poll fallback every
30s)` on startup and `playlist_worker: processed N job(s)` whenever it drains
one or more queued jobs. A queued/failed job's live state is queryable
directly: `SELECT * FROM playlist_jobs ORDER BY created_at DESC LIMIT 20;` —
`status` is one of `queued`/`running`/`complete`/`failed`, and `failed` rows
carry their exception text in `error`. (Dead-letter *visibility* beyond this
queryable column — retry UI, alerting — is deferred; see ADR 0006.)

**Crash recovery is automatic, no manual DB fix-up needed.** If the process
dies mid-job (`systemctl restart`, OOM, a host reboot), the job it was
running is left in `running` — every loop iteration (so effectively on
startup, and again each wake/poll tick) resets any `running` row older than
10 minutes back to `queued`, logging `playlist_worker: reclaimed N stale
running job(s)`. It's then picked up by the ordinary dequeue path like any
other queued job. A `running` row younger than 10 minutes is left alone
(presumed still genuinely in flight).

**Disable in an emergency** (stops new playlist generation entirely; jobs pile
up as `queued` until the worker restarts, they don't get dropped):

```bash
sudo systemctl stop mysterymixclub-playlist-worker
```

Re-enable/restart with `sudo systemctl start mysterymixclub-playlist-worker`.

---

## Enabling Apple Music (MYS-104)

Apple Music is **off** until three credentials are present, and the app treats
that as a normal state: the mystery mix page renders no Apple UI at all, and Apple
per-track links fall back to the keyless iTunes lookup. So this can be done long
after the code ships, and skipping it breaks nothing.

**Credentials come from the Apple Developer portal** (paid membership required).
Certificates, Identifiers & Profiles → **Identifiers → ＋ → Media IDs** first —
the Keys page reports *"no identifiers available that can be associated with the
key"* until a Media ID exists, and an App ID with the MusicKit capability ticked
does **not** satisfy it. Then Keys → ＋ → Media Services (MusicKit) → download
the `.p8`. **That download is one-time and non-recoverable** — store the original
in a password manager before doing anything else.

- `APPLE_MUSIC_TEAM_ID` — membership details page, 10 chars
- `APPLE_MUSIC_KEY_ID` — the 10 chars in the `AuthKey_XXXXXXXXXX.p8` filename
- `APPLE_MUSIC_PRIVATE_KEY` — the `.p8` PEM contents

On the Droplet, add all three to the env file. The PEM must be **one quoted
line** with literal `\n` between PEM lines (the app un-escapes them —
`apple_music_token.py`):

```bash
sudo nano /etc/mysterymixclub/staging.env
# APPLE_MUSIC_TEAM_ID=A1B2C3D4E5
# APPLE_MUSIC_KEY_ID=XXXXXXXXXX
# APPLE_MUSIC_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMIGT...\n-----END PRIVATE KEY-----"

sudo systemctl restart mysterymixclub-api
```

To flatten the PEM to that one-line form without pasting it through anything:

```bash
awk '{printf "%s\\n", $0}' AuthKey_XXXXXXXXXX.p8
```

**Verify** — the endpoint returns a token only when all three are valid and
Apple accepts the signature. It requires a logged-in user's bearer token:

```bash
curl -s https://staging.mysterymixclub.com/api/v1/apple-music/developer-token \
     -H "Authorization: Bearer <access-token>"
# {"token":"eyJ..."}   → working
# {"token":null}       → unconfigured or the key can't sign; check the journal
```

A restart is required: the settings and the token service are cached per
process, so editing the env file alone changes nothing.

---

## Enabling Google Sign-In (MysteryMixClub-ali8, ADR 0007)

Google Sign-In is **off** until all three credentials are present, the same
"gap is a supported state" pattern as Apple Music above: the login screen
renders no Google button, and magic link / password (once shipped) keep
working exactly as before. So this can be done any time after the code ships,
independently of it, and skipping it breaks nothing.

**Credentials come from the Google Cloud console** (console.cloud.google.com,
any Google account — no paid membership required, unlike Apple).

1. Create (or pick) a project, then **APIs & Services → OAuth consent
   screen**. Choose **External** user type, fill in the app name/support
   email, and add the `email` and `profile` scopes (nothing else needed).
   While the app is in **Testing** mode only explicitly-added test users can
   sign in — fine for early staging use, but production needs the app moved
   to **Production** and, because MysteryMixClub already has live users at
   that point, **submitted for Google's verification review**. That review
   has its own lead time outside our control — start it early, don't treat it
   as a same-day deploy step (see ADR 0007's "Revisit if").
2. **APIs & Services → Credentials → + Create Credentials → OAuth client ID**,
   application type **Web application**. Add an **Authorized redirect URI**
   pointing at this environment's callback:
   `https://staging.mysterymixclub.com/api/v1/auth/google/callback`. It must
   match `GOOGLE_REDIRECT_URI` below **exactly**, including scheme and path.
3. Google shows the **Client ID** and **Client secret** once the client is
   created (both are re-viewable later from the Credentials page, unlike
   Apple's one-time `.p8` download).

On the Droplet, add all three to the env file:

```bash
sudo nano /etc/mysterymixclub/staging.env
# GOOGLE_CLIENT_ID=xxxxxxxxxx.apps.googleusercontent.com
# GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxxxxxxxxxx
# GOOGLE_REDIRECT_URI=https://staging.mysterymixclub.com/api/v1/auth/google/callback

sudo systemctl restart mysterymixclub-api
```

**Verify** — the login screen should now render the Google button, and
starting the flow should redirect to Google's consent screen rather than
erroring:

```bash
curl -s https://staging.mysterymixclub.com/api/v1/auth/google/login
# a redirect (302) to accounts.google.com when configured;
# 404 when GOOGLE_CLIENT_ID is unset, same "hidden" behavior as Apple Music
```

A restart is required: settings are cached per process, so editing the env
file alone changes nothing.

**Use a separate OAuth client per environment** — never share
`GOOGLE_CLIENT_SECRET` across staging and prod, and each needs its own
Authorized redirect URI registered on its own client (see `prod.env.example`).

---

## Enabling push notifications (MysteryMixClub-4vii.25/27, IOS-04)

Push is **off** until both credentials are present, the same "gap is a
supported state" pattern as Apple Music and Google above: every recipient's
send is skipped without ever calling APNs (with one `push send: skipped N
recipient(s), apns credentials are not configured` warning in the journal),
no user-visible error, no crash. So this can be done any time after the code ships,
independently of it, and skipping it breaks nothing except the notifications
themselves.

**Credentials come from the Apple Developer portal** (the same paid
membership Apple Music and Sign in with Apple already need — no new
enrollment). Two separate one-time steps, both required:

1. **Certificates, Identifiers & Profiles → Identifiers →** this app's App ID
   (`com.mysterymixclub.app`) **→ check "Push Notifications" →** Save. Without
   this, code signing with the `aps-environment` entitlement `App.entitlements`
   already carries fails (or silently does nothing on-device), the same
   category of gotcha Sign in with Apple's own capability step has.
   Regenerate/re-download the provisioning profile afterward.
2. **Keys → ＋ → check "Apple Push Notifications service (APNs)" →** download
   the `.p8`. **This download is one-time and non-recoverable** — store the
   original in a password manager before doing anything else. Use a
   **separate** key from Apple Music's MusicKit key (different service,
   don't reuse); each environment can share one key or use its own,
   but never share the `.p8` file itself the way `SECRET_KEY` must never be
   shared.

- `APPLE_PUSH_KEY_ID` — the 10 chars in the downloaded `AuthKey_XXXXXXXXXX.p8`
  filename
- `APPLE_PUSH_PRIVATE_KEY` — the `.p8` PEM contents
- Team ID is **not** a separate value here — the push token service reuses
  `APPLE_MUSIC_TEAM_ID` (already on the box if Apple Music is enabled;
  otherwise it's still just the membership details page's Team ID, no Apple
  Music setup required to fill it in).

On the Droplet, add both to the env file. Same one-line, `\n`-escaped PEM
convention as `APPLE_MUSIC_PRIVATE_KEY`:

```bash
sudo nano /etc/mysterymixclub/staging.env
# APPLE_MUSIC_TEAM_ID=A1B2C3D4E5    # already present if Apple Music is on
# APPLE_PUSH_KEY_ID=YYYYYYYYYY
# APPLE_PUSH_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMIGT...\n-----END PRIVATE KEY-----"

sudo systemctl restart mysterymixclub-api
```

**Verify** — there is no client-facing endpoint to curl (unlike Apple Music's
developer-token route: a provider token is only ever used server-to-APNs,
never handed to the frontend). Two levels of check:

1. **Config sanity**, without a real device. First, does Apple *accept* the
   credentials? (Minting a JWT proves only that the key can sign.)
   ```bash
   sudo -u mysterymixclub bash -c '
     cd /home/mysterymixclub/app/backend &&
     set -a && source /etc/mysterymixclub/staging.env && set +a &&
     .venv/bin/python -m scripts.probe_apns_environment --check-credentials'
   ```
   `credentials ACCEPTED` means a token that belongs to no device got
   `BadDeviceToken` from the production gateway, which happens only after Apple
   authenticated the provider (Apple documents a bad key, Key ID or Team ID as a
   `403`; only the accepted case has been observed here).
   It does not validate the topic (APNs checks the device token first), and a
   key restricted to production only will show a sandbox `403` that is noted,
   not treated as a failure. Nothing is sent to anyone. Then the local signing
   check on its own:
   ```bash
   cd /home/mysterymixclub/app/backend && source .venv/bin/activate
   set -a && source /etc/mysterymixclub/staging.env && set +a
   python3 -c "
   import asyncio
   from app.config import get_settings
   from app.services.apple_push_token import build_apple_push_token_service
   svc = build_apple_push_token_service(get_settings())
   print('configured:', svc.is_configured)
   print(asyncio.run(svc.get_provider_token())[:20] + '...')
   "
   ```
   Raises `ApplePushTokenError` on a bad key/PEM; prints a token prefix on
   success. To find out which APNs environment a *registered device's* token is
   in, see "Which APNs environment is a build in?" in `docs/ios/README.md`.
2. **The real signal**: register a device via the app (Settings → enable
   notifications, or the onboarding auto-prompt), then trigger any mix
   lifecycle event (submit, vote, or wait for a deadline reminder) and check
   the journal:
   ```bash
   sudo journalctl -u mysterymixclub-api -u mysterymixclub-advance-mixes --since "5 min ago" | grep "push send"
   ```
   Two units send pushes: the API (`mysterymixclub-api`, lifecycle events
   triggered by a request) and the deadline job (`mysterymixclub-advance-mixes`,
   reminders and deadline advances), so grep both. **The API unit surfaces only
   WARNING-and-above records** (its INFO logging is switched on in development
   only), so its journal shows sends that were *skipped, rejected or retired*
   and cannot show one that succeeded. The deadline job's unit does run at INFO
   and also logs `push send: accepted by apns` for each accepted request.
   **A missing line in the API journal therefore proves nothing**: it can mean
   APNs accepted the request, or that no send was attempted at all (no
   recipient had a registered device, or the event never fired). And even a 200
   from APNs is acceptance, not delivery -- the phone may be offline, in a Focus
   mode, or have notifications switched off. The confirmation that push works
   is the notification appearing on the device.

   | Journal line | Meaning |
   |---|---|
   | `push send: accepted by apns` (deadline job unit only) | APNs returned 200. Acceptance, not delivery. |
   | `push send: skipped N recipient(s), apns credentials are not configured` | The key/Key ID are missing from the running process. |
   | `push send: no apns topic (bundle id) is configured` | `APPLE_SIGN_IN_BUNDLE_ID` resolved to an empty string. |
   | `push send: apns rejected the request (status=403 reason=InvalidProviderToken)` | The key / Key ID / Team ID pairing is wrong (`ExpiredProviderToken`, `Forbidden` and similar 403 reasons are the same family). |
   | `push send: apns rejected the request (status=400 reason=BadTopic)` (or `TopicDisallowed`, `PayloadEmpty`, ...) | A request or configuration problem -- the topic, payload or headers. **The device token is left alone.** |
   | `push send: apns rejected the request (status=429 ...)` / `status=5xx` | Throttling or an APNs outage. Nothing is retired. |
   | `push send: apns rejected the request (status=400 reason=unreadable)` | The response body was not a readable APNs error. Nothing is retired. |
   | `push send: apns answered BadDeviceToken but has not yet accepted this topic in this process, so the token is kept` | APNs rejected the token, but this process has not yet seen a 200 for the topic, so a wrong topic or credentials cannot be ruled out. Nothing is deleted. |
   | `push send: retired a registration apns reports as dead (status=410 reason=Unregistered)` | APNs said the token is no longer active for this app (a `BadDeviceToken` also retires once the topic has been accepted). The registration was deleted. |
   | `push send: did not retire: the registration was newer than the verdict, reassigned to another account, or already removed` | A dead-token verdict arrived but the row it named was not the one to delete; nothing was removed. |

   Two caveats on `BadDeviceToken`. The "topic accepted" memory is **per
   process** -- each API worker process, each run of the deadline job and every
   restart or deploy starts without it -- so whether a dead token is retired
   on a given send depends on whether that process has already had a send
   accepted. That errs on the safe side (rows are kept, never wrongly
   deleted). And it proves the topic and credentials line up, **not** the
   token's environment: APNs answers `BadDeviceToken` for a token minted for
   the other environment too, so once a process has an accepted send, a
   sandbox token (from an Xcode debug build) is retired as well. That is
   right for a backend that only ever talks to the production gateway, but it
   means such tokens never receive anything; see `docs/adr/0033`.

   No device token, provider JWT or notification payload is ever logged.

A restart is required: settings and the token service are cached per
process, so editing the env file alone changes nothing.

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
- **Deadline job status / logs:** `systemctl list-timers mysterymixclub-advance-mixes.timer`
  and `sudo journalctl -u mysterymixclub-advance-mixes.service -f` (see §7). Mixes
  not advancing at their deadline → check the timer is enabled and the run summary
  for `errors=`.

---

## If this Droplet is ever compromised

This is where real beta user data actually lives (magic-link emails, songs,
notes, votes) — see `docs/security/breach-notification-runbook.md` for what to
do: containment steps, scoping the exposure, and the GDPR 72-hour authority
notification / user notification process (MYS-187).

## Where this Droplet actually is

Its DO region isn't recorded here — see `docs/security/data-residency.md`
(MYS-188) for what's confirmed, what's inferred, and the international-transfer
safeguard reasoning if EU/EEA/UK users are ever in scope.
