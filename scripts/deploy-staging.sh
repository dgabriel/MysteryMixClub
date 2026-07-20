#!/usr/bin/env bash
#
# Pull the latest `develop` and restart the MysteryMixClub staging app on the
# Droplet. Invoked by .github/workflows/deploy-staging.yml over SSH, or run by
# hand from the repo checkout. Safe to re-run (idempotent).
#
# Requires the invoking user to have passwordless sudo for:
#   systemctl restart mysterymixclub-api
#   systemctl disable --now mysterymixclub-advance-rounds.timer
#   rm -f /etc/systemd/system/mysterymixclub-advance-rounds.{service,timer}
#   cp scripts/mysterymixclub-advance-mixes.{service,timer} /etc/systemd/system/
#   systemctl daemon-reload
#   systemctl enable --now mysterymixclub-advance-mixes.timer
# (the advance-rounds steps retire the pre-MYS-195 unit name; the advance-mixes
# steps keep the MYS-145/162 deadline job's unit files and timer current.)
# The web root is owned by the deploy user (see bootstrap-droplet.sh), so the
# frontend publish step needs no sudo. (See docs/staging-setup.md.)
set -euo pipefail

ENV_FILE="${ENV_FILE:-/etc/mysterymixclub/staging.env}"
WEB_ROOT="${WEB_ROOT:-/var/www/mysterymixclub}"

# Resolve the repo root from this script's location so it works from any CWD.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

echo "==> Syncing to origin/develop"
# Force the checkout to exactly match origin/develop, regardless of the current
# branch or any local drift — a deploy target carries no local commits. This
# keeps the deploy idempotent and safe to re-run.
git fetch --prune origin
git checkout -f -B develop origin/develop

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

echo "==> Restarting the API service"
sudo systemctl restart mysterymixclub-api

echo "==> Retiring the pre-rename advance-rounds unit (MYS-195)"
# Disable and remove the old unit name before installing the new one, so a
# stale job never keeps running alongside (or instead of) the renamed one.
# Idempotent: safe to re-run, and safe once the old unit is already gone —
# `disable --now` on a unit systemd doesn't know about just errors, which the
# `|| true` swallows, and `rm -f` is a no-op on a missing file.
# Both commands require the sudoers grant added for MYS-195 (see
# docs/staging-setup.md §6) — `|| true` also covers a Droplet whose sudoers
# file predates that grant, so a stale grant never hard-fails the deploy; on
# such a Droplet the old unit just lingers (and its ExecStart will start
# erroring in journalctl, since advance_rounds.py no longer exists) until the
# sudoers file is updated by hand.
sudo systemctl disable --now mysterymixclub-advance-rounds.timer 2>/dev/null || true
sudo rm -f /etc/systemd/system/mysterymixclub-advance-rounds.service \
  /etc/systemd/system/mysterymixclub-advance-rounds.timer 2>/dev/null || true

echo "==> Installing/refreshing the deadline force-advance job (MYS-145/162)"
# Keep the job's unit files current with the checkout and its timer enabled, so
# code and schedule changes take effect on deploy. Idempotent: re-copying and
# re-enabling are no-ops when nothing changed.
sudo cp "${REPO_ROOT}/scripts/mysterymixclub-advance-mixes.service" /etc/systemd/system/
sudo cp "${REPO_ROOT}/scripts/mysterymixclub-advance-mixes.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mysterymixclub-advance-mixes.timer

echo "==> Building and publishing the frontend"
cd ../frontend
npm ci
# Build the SPA to call the API same-origin: an empty base yields relative
# /api/v1/... URLs, which nginx proxies to the backend. (A baked-in absolute
# host like http://localhost:8000 would resolve against the visitor's browser.)
# Honors VITE_API_BASE_URL from the sourced env if it is set there.
VITE_API_BASE_URL="${VITE_API_BASE_URL-}" npm run build
# Replace the web root contents rather than overlaying — Vite emits content-hashed
# asset names, so a plain copy would leave stale bundles behind to accumulate.
find "${WEB_ROOT}" -mindepth 1 -delete
cp -r dist/* "${WEB_ROOT}/"

echo "==> Deploy complete"
