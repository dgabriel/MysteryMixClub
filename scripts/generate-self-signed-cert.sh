#!/usr/bin/env bash
#
# Generate a self-signed TLS certificate for the staging Droplet when no domain /
# DNS is available yet. Browsers show a warning testers must click through.
# Replace with a Let's Encrypt cert (`certbot --nginx -d <domain>`) once a domain
# points at the box. Safe to re-run (won't overwrite an existing cert).
#
#   sudo bash scripts/generate-self-signed-cert.sh
#   # or for a hostname SAN:
#   CERT_CN=staging.mysterymixclub.com CERT_SAN_TYPE=DNS sudo -E bash scripts/generate-self-signed-cert.sh
set -euo pipefail

CERT_DIR="${CERT_DIR:-/etc/ssl/mmc-staging}"
CERT_CN="${CERT_CN:-67.207.81.183}"        # IP or hostname clients connect to
CERT_SAN_TYPE="${CERT_SAN_TYPE:-IP}"       # IP or DNS, to match CERT_CN
DAYS="${DAYS:-825}"

if [[ ${EUID} -ne 0 ]]; then
  echo "ERROR: run as root (sudo)." >&2
  exit 1
fi

install -d -m 0700 "${CERT_DIR}"
if [[ -f "${CERT_DIR}/privkey.pem" && -f "${CERT_DIR}/fullchain.pem" ]]; then
  echo "Certificate already present in ${CERT_DIR}, skipping."
  exit 0
fi

openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "${CERT_DIR}/privkey.pem" \
  -out "${CERT_DIR}/fullchain.pem" \
  -days "${DAYS}" \
  -subj "/CN=${CERT_CN}" \
  -addext "subjectAltName=${CERT_SAN_TYPE}:${CERT_CN}"
chmod 600 "${CERT_DIR}/privkey.pem"

echo "Self-signed certificate written to ${CERT_DIR} (CN=${CERT_CN}, valid ${DAYS} days)."
