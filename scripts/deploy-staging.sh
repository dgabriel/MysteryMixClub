#!/usr/bin/env bash
#
# Pull the latest `develop` and restart the MysteryMixClub staging app on the
# Droplet. Invoked by .github/workflows/deploy-staging.yml over SSH, or run by
# hand from the repo checkout. Safe to re-run (idempotent).
#
# Requires the invoking user to have passwordless sudo for:
#   systemctl restart mysterymixclub-api
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

echo "==> Building and publishing the frontend"
cd ../frontend
npm ci
npm run build
cp -r dist/* "${WEB_ROOT}/"

echo "==> Deploy complete"
