#!/usr/bin/env bash
#
# Pull the latest `main` and reload the MysteryMixClub production app on the
# Droplet. Invoked by .github/workflows/deploy-prod.yml, which runs directly
# on the Droplet via a self-hosted GitHub Actions runner (no SSH — see
# docs/prod-setup.md), or run by hand from the repo checkout. Safe to re-run
# (idempotent).
#
# Requires the invoking user to have passwordless sudo for:
#   systemctl reload mysterymixclub-api
#   systemctl restart mysterymixclub-api (first-deploy fallback, MYS-259 — see below)
#   cp scripts/mysterymixclub-advance-mixes-prod.{service,timer} /etc/systemd/system/mysterymixclub-advance-mixes.{service,timer}
#   cp scripts/mysterymixclub-playlist-worker-prod.service /etc/systemd/system/mysterymixclub-playlist-worker.service
#   systemctl daemon-reload
#   systemctl enable --now mysterymixclub-advance-mixes.timer
#   systemctl restart mysterymixclub-playlist-worker (MYS-258, ADR 0006 —
#     persistent process, not timer-driven; restart both applies new code and
#     starts it on the first deploy after bootstrap installed-but-didn't-start it)
# The web root is owned by the deploy user (see bootstrap-droplet-prod.sh), so
# the frontend publish step needs no sudo. (See docs/prod-setup.md.)
#
# The frontend is no longer built here (MYS-259) — a hosted GitHub Actions
# runner builds it (.github/workflows/deploy-prod.yml's build-frontend job)
# and the workflow downloads the dist/ artifact into frontend/dist before this
# script runs. Building `npm ci && npm run build` on this 2 GB droplet during
# every deploy risked OOMing the app host itself; this script now only
# publishes an already-built bundle.
#
# Mirrors scripts/deploy-staging.sh, which still builds the frontend on-box —
# see docs/ci-cd.md and docs/prod-setup.md for why prod moved this into CI
# and staging (for now) did not.  Deliberately does NOT carry staging's
# advance-rounds -> advance-mixes retirement step (MYS-195) — production never
# ran the pre-rename unit, so there is nothing to retire.
set -euo pipefail

ENV_FILE="${ENV_FILE:-/etc/mysterymixclub/prod.env}"
WEB_ROOT="${WEB_ROOT:-/var/www/mysterymixclub}"

# Resolve the repo root from this script's location so it works from any CWD.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

echo "==> Syncing to origin/main"
# Force the checkout to exactly match origin/main, regardless of the current
# branch or any local drift — a deploy target carries no local commits. This
# keeps the deploy idempotent and safe to re-run.
git fetch --prune origin
git checkout -f -B main origin/main

echo "==> Installing backend dependencies and running migrations"
cd backend
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -e .
# Alembic reads DATABASE_URL from application settings (migrations/env.py), so
# load the runtime env that systemd normally injects before upgrading the schema.
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a
alembic upgrade head

echo "==> Reloading the API service (graceful — MYS-259)"
# `reload` sends the unit's ExecReload (SIGHUP), which tells gunicorn's master
# to boot a fresh set of workers on the new code and only then gracefully
# drain and kill the old ones — in-flight requests finish instead of being
# dropped, unlike a hard restart.
#
# Attempt reload first and fall back to a real restart on ANY failure, rather
# than pre-deciding via `systemctl is-active`: reload can be inapplicable for
# two different reasons, and an is-active check only catches one of them.
#   1. The unit isn't active yet (fresh bootstrap, before docs/prod-setup.md
#      §3's one-time `enable --now`) — is-active is false, reload would fail.
#   2. The unit IS active, but is still the pre-MYS-259 unit definition with
#      no ExecReload= at all (i.e. this is the first deploy after merging
#      MYS-259, before the one-time manual cutover in prod-setup.md §3 has
#      been done) — is-active is TRUE here, so a naive is-active guard would
#      still attempt `reload` and hit systemd's "Job type reload is not
#      applicable" error, which is fatal under `set -e` and would abort the
#      whole deploy AFTER the alembic migration above already ran.
# Checking the reload command's own exit status, not a proxy for it, handles
# both cases uniformly and stays correct once the unit really is the new
# gunicorn one (where reload always succeeds and this fallback never fires).
if ! sudo systemctl reload mysterymixclub-api; then
  echo "    reload not applicable (first deploy after bootstrap, or the live" >&2
  echo "    unit predates graceful-reload support, MYS-259) — restarting instead" >&2
  sudo systemctl restart mysterymixclub-api
fi

echo "==> Installing/refreshing the deadline force-advance job (MYS-145/162)"
# Keep the job's unit files current with the checkout and its timer enabled, so
# code and schedule changes take effect on deploy. Idempotent: re-copying and
# re-enabling are no-ops when nothing changed.
sudo cp "${REPO_ROOT}/scripts/mysterymixclub-advance-mixes-prod.service" /etc/systemd/system/mysterymixclub-advance-mixes.service
sudo cp "${REPO_ROOT}/scripts/mysterymixclub-advance-mixes-prod.timer" /etc/systemd/system/mysterymixclub-advance-mixes.timer
sudo systemctl daemon-reload
sudo systemctl enable --now mysterymixclub-advance-mixes.timer

echo "==> Installing/refreshing and restarting the playlist worker (MYS-258, ADR 0006)"
# Persistent process (not timer-driven), so a `restart` — rather than the
# deadline job's `enable --now` — both applies new code and starts it on the
# first deploy after bootstrap installed-but-didn't-start it.
sudo cp "${REPO_ROOT}/scripts/mysterymixclub-playlist-worker-prod.service" /etc/systemd/system/mysterymixclub-playlist-worker.service
sudo systemctl daemon-reload
sudo systemctl enable mysterymixclub-playlist-worker
sudo systemctl restart mysterymixclub-playlist-worker

echo "==> Publishing the frontend (built in CI, not here — MYS-259)"
cd ../frontend
# .github/workflows/deploy-prod.yml's build-frontend job builds the SPA on a
# hosted runner and downloads the dist/ artifact here (frontend/dist) before
# invoking this script — nothing in this script builds it anymore. Fail loudly
# rather than silently publishing an empty/missing bundle if that hand-off
# didn't happen (e.g. someone runs this script by hand without the artifact
# in place).
if [[ ! -d dist ]] || [[ -z "$(ls -A dist 2>/dev/null)" ]]; then
  echo "ERROR: frontend/dist is missing or empty. This script no longer builds" >&2
  echo "       the frontend (MYS-259) — it expects the CI build-frontend job's" >&2
  echo "       artifact already downloaded to frontend/dist. See" >&2
  echo "       .github/workflows/deploy-prod.yml and docs/prod-setup.md." >&2
  exit 1
fi
# Replace the web root contents rather than overlaying — Vite emits content-hashed
# asset names, so a plain copy would leave stale bundles behind to accumulate.
find "${WEB_ROOT}" -mindepth 1 -delete
cp -r dist/* "${WEB_ROOT}/"

echo "==> Deploy complete"
