#!/usr/bin/env bash
#
# One-time bootstrap for a fresh Ubuntu 24.04 DigitalOcean Droplet that hosts
# the MysteryMixClub *production* environment. Safe to re-run (idempotent).
#
# Run as root on the Droplet, passing the DB password and your admin SSH CIDR
# in the environment:
#   PROD_DB_PASSWORD='...' ADMIN_SSH_CIDR='203.0.113.4/32' \
#     sudo -E bash scripts/bootstrap-droplet-prod.sh
#
# Provisions: system packages, the `mysterymixclub` service user, the prod
# Postgres role + database, the app checkout + virtualenv, the web root, and
# the host firewall. See docs/prod-setup.md for the full runbook.
#
# Differs from bootstrap-droplet.sh (staging) in two deliberate ways, per the
# staging anti-patterns flagged in infra/terraform/README.md:
#   1. SSH is scoped to ADMIN_SSH_CIDR at the host firewall too (defense in
#      depth alongside the DO cloud firewall from Terraform), not opened to
#      the whole internet.
#   2. Checks out `main`, not `develop` — production tracks the promoted branch.
set -euo pipefail

# --- Configuration (override via environment) ---------------------------------
APP_USER="${APP_USER:-mysterymixclub}"
APP_ROOT="${APP_ROOT:-/home/${APP_USER}/app}"
WEB_ROOT="${WEB_ROOT:-/var/www/mysterymixclub}"
ENV_DIR="${ENV_DIR:-/etc/mysterymixclub}"
REPO_URL="${REPO_URL:-https://github.com/dgabriel/MysteryMixClub.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"

PROD_DB_NAME="${PROD_DB_NAME:-mysterymixclub_prod}"
PROD_DB_USER="${PROD_DB_USER:-mmc_prod}"
PROD_DB_PASSWORD="${PROD_DB_PASSWORD:-}"
ADMIN_SSH_CIDR="${ADMIN_SSH_CIDR:-}"

if [[ ${EUID} -ne 0 ]]; then
  echo "ERROR: run as root, e.g. 'sudo -E bash $0'." >&2
  exit 1
fi
if [[ -z "${PROD_DB_PASSWORD}" ]]; then
  echo "ERROR: PROD_DB_PASSWORD must be set in the environment." >&2
  exit 1
fi
if [[ -z "${ADMIN_SSH_CIDR}" ]]; then
  echo "ERROR: ADMIN_SSH_CIDR must be set (e.g. '203.0.113.4/32') — production" >&2
  echo "       does not open SSH to the whole internet. Use the same CIDR as" >&2
  echo "       ssh_allowed_cidrs in infra/terraform/envs/prod/terraform.tfvars." >&2
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
  git curl ca-certificates

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

echo "==> Provisioning the production Postgres role and database"
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${PROD_DB_USER}'" | grep -q 1; then
  echo "    role exists; refreshing password"
  sudo -u postgres psql -c "ALTER ROLE ${PROD_DB_USER} WITH LOGIN PASSWORD '${PROD_DB_PASSWORD}';"
else
  sudo -u postgres psql -c "CREATE ROLE ${PROD_DB_USER} WITH LOGIN PASSWORD '${PROD_DB_PASSWORD}';"
fi
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${PROD_DB_NAME}'" | grep -q 1; then
  echo "    database exists, skipping"
else
  sudo -u postgres createdb -O "${PROD_DB_USER}" "${PROD_DB_NAME}"
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

echo "==> Installing the deadline force-advance job (systemd timer, MYS-145/162)"
# Arm the timer now; it activates on the next boot / first deploy. `enable` (not
# --now) so the job doesn't fire before the runtime env file below is populated.
install -m 0644 "${APP_ROOT}/scripts/mysterymixclub-advance-mixes-prod.service" /etc/systemd/system/mysterymixclub-advance-mixes.service
install -m 0644 "${APP_ROOT}/scripts/mysterymixclub-advance-mixes-prod.timer" /etc/systemd/system/mysterymixclub-advance-mixes.timer
systemctl daemon-reload
systemctl enable mysterymixclub-advance-mixes.timer

echo "==> Configuring the firewall (ufw) — SSH scoped to ${ADMIN_SSH_CIDR}"
# Defense in depth alongside the DO cloud firewall (Terraform-managed): even if
# the cloud firewall were ever misconfigured or removed, the host itself still
# refuses SSH from anywhere but the admin CIDR. This is the fix for the exact
# anti-pattern flagged on staging (MYS-224), applied here from day one.
ufw allow from "${ADMIN_SSH_CIDR}" to any port 22 proto tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

cat <<EOF

Bootstrap complete. Remaining steps (see docs/prod-setup.md):
  1. Populate ${ENV_DIR}/prod.env from scripts/prod.env.example
  2. Install the systemd unit (scripts/mysterymixclub-api-prod.service, as
     mysterymixclub-api.service)
  3. Point DNS (mysterymixclub.com + www) at this Droplet, install the nginx
     site (scripts/nginx-mysterymixclub-prod.conf), then run certbot
  4. Once the env is populated, start the deadline-job timer:
     systemctl enable --now mysterymixclub-advance-mixes.timer

EOF
