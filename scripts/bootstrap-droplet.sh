#!/usr/bin/env bash
#
# One-time bootstrap for a fresh Ubuntu 24.04 DigitalOcean Droplet that hosts the
# MysteryMixClub *staging* environment. Safe to re-run (idempotent).
#
# Run as root on the Droplet, passing the DB password in the environment:
#   STAGING_DB_PASSWORD='...' sudo -E bash scripts/bootstrap-droplet.sh
#
# Provisions: system packages, the `mysterymixclub` service user, the staging
# Postgres role + database, the app checkout + virtualenv, the web root, and the
# firewall. See docs/staging-setup.md for the full runbook.
set -euo pipefail

# --- Configuration (override via environment) ---------------------------------
APP_USER="${APP_USER:-mysterymixclub}"
APP_ROOT="${APP_ROOT:-/home/${APP_USER}/app}"
WEB_ROOT="${WEB_ROOT:-/var/www/mysterymixclub}"
ENV_DIR="${ENV_DIR:-/etc/mysterymixclub}"
REPO_URL="${REPO_URL:-https://github.com/dgabriel/MysteryMixClub.git}"
REPO_BRANCH="${REPO_BRANCH:-develop}"

STAGING_DB_NAME="${STAGING_DB_NAME:-mysterymixclub_staging}"
STAGING_DB_USER="${STAGING_DB_USER:-mmc_staging}"
STAGING_DB_PASSWORD="${STAGING_DB_PASSWORD:-}"

if [[ ${EUID} -ne 0 ]]; then
  echo "ERROR: run as root, e.g. 'sudo -E bash $0'." >&2
  exit 1
fi
if [[ -z "${STAGING_DB_PASSWORD}" ]]; then
  echo "ERROR: STAGING_DB_PASSWORD must be set in the environment." >&2
  exit 1
fi

echo "==> Updating apt and installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
  nginx \
  python3-pip python3-venv \
  postgresql postgresql-contrib \
  certbot python3-certbot-nginx \
  git apache2-utils curl ca-certificates   # apache2-utils provides htpasswd for basic auth

# Node.js 20 from NodeSource. Ubuntu 24.04's apt ships Node 18, but the frontend
# requires Node 20+ — building the SPA on 18 silently produces a broken bundle
# (e.g. VITE_API_BASE_URL handling differs). Guarded so re-runs are no-ops.
if ! node --version 2>/dev/null | grep -q '^v20\.'; then
  echo "==> Installing Node.js 20 (NodeSource)"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

echo "==> Creating system user '${APP_USER}'"
if id -u "${APP_USER}" >/dev/null 2>&1; then
  echo "    user already exists, skipping"
else
  useradd --system --create-home --shell /bin/bash "${APP_USER}"
fi

echo "==> Enabling and starting postgresql + nginx"
systemctl enable --now postgresql
systemctl enable --now nginx

echo "==> Provisioning the staging Postgres role and database"
# createuser/createdb are not idempotent on their own; guard with catalog lookups.
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${STAGING_DB_USER}'" | grep -q 1; then
  echo "    role exists; refreshing password"
  sudo -u postgres psql -c "ALTER ROLE ${STAGING_DB_USER} WITH LOGIN PASSWORD '${STAGING_DB_PASSWORD}';"
else
  sudo -u postgres psql -c "CREATE ROLE ${STAGING_DB_USER} WITH LOGIN PASSWORD '${STAGING_DB_PASSWORD}';"
fi
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${STAGING_DB_NAME}'" | grep -q 1; then
  echo "    database exists, skipping"
else
  sudo -u postgres createdb -O "${STAGING_DB_USER}" "${STAGING_DB_NAME}"
fi

echo "==> Creating directories"
install -d -o "${APP_USER}" -g "${APP_USER}" "$(dirname "${APP_ROOT}")"
install -d -o "${APP_USER}" -g "${APP_USER}" "${WEB_ROOT}"
install -d -o root -g root -m 0750 "${ENV_DIR}"

echo "==> Checking out the application (branch: ${REPO_BRANCH})"
if [[ -d "${APP_ROOT}/.git" ]]; then
  echo "    repo already cloned; fetching latest"
  sudo -u "${APP_USER}" git -C "${APP_ROOT}" fetch origin "${REPO_BRANCH}"
  sudo -u "${APP_USER}" git -C "${APP_ROOT}" checkout "${REPO_BRANCH}"
  sudo -u "${APP_USER}" git -C "${APP_ROOT}" reset --hard "origin/${REPO_BRANCH}"
else
  sudo -u "${APP_USER}" git clone --branch "${REPO_BRANCH}" "${REPO_URL}" "${APP_ROOT}"
fi

echo "==> Creating the backend virtualenv and installing dependencies"
if [[ ! -d "${APP_ROOT}/backend/.venv" ]]; then
  sudo -u "${APP_USER}" python3 -m venv "${APP_ROOT}/backend/.venv"
fi
sudo -u "${APP_USER}" "${APP_ROOT}/backend/.venv/bin/pip" install --upgrade pip
sudo -u "${APP_USER}" bash -c "cd '${APP_ROOT}/backend' && .venv/bin/pip install -e ."

echo "==> Configuring the firewall (ufw)"
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

cat <<EOF

Bootstrap complete. Remaining steps (see docs/staging-setup.md):
  1. Populate ${ENV_DIR}/staging.env from scripts/staging.env.example
  2. Install the systemd unit (scripts/mysterymixclub-api.service)
  3. Install the nginx site + create the basic-auth file, then run certbot

EOF
