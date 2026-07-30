#!/usr/bin/env bash
# ONE-TIME loader: turn output/claude_code_backfill.om (from extract_usage.py)
# into Prometheus TSDB blocks and copy them into the running Prometheus
# container's data volume. Safe to re-run against a fresh .om file; Prometheus
# does not deduplicate blocks, so if you re-run extract_usage.py, prefer
# giving it a --before cutoff rather than reloading overlapping data twice.
#
# Prerequisites:
#   - The observability docker-compose stack is up (docker-compose up -d),
#     or --start will start just prometheus for you.
#   - output/claude_code_backfill.om exists (run extract_usage.py first).
#
# Usage:
#   ./load_backfill.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OBS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OM_FILE="$SCRIPT_DIR/output/claude_code_backfill.om"
BLOCKS_DIR="$SCRIPT_DIR/output/blocks"
PROM_IMAGE="prom/prometheus:v3.13.1"
CONTAINER_NAME="mmc-agent-obs-prometheus"

if [[ ! -f "$OM_FILE" ]]; then
  echo "ERROR: $OM_FILE not found. Run extract_usage.py first." >&2
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "ERROR: $CONTAINER_NAME is not running. Start the stack first:" >&2
  echo "  (cd $OBS_DIR && docker-compose up -d)" >&2
  exit 1
fi

echo "1/4  Validating OpenMetrics syntax..."
docker run --rm --entrypoint promtool \
  -v "$SCRIPT_DIR/output:/data:ro" \
  "$PROM_IMAGE" check metrics < "$OM_FILE"

echo "2/4  Building TSDB blocks from $OM_FILE..."
rm -rf "$BLOCKS_DIR"
mkdir -p "$BLOCKS_DIR"
docker run --rm \
  -v "$SCRIPT_DIR/output:/in:ro" \
  -v "$BLOCKS_DIR:/out" \
  --entrypoint promtool "$PROM_IMAGE" \
  tsdb create-blocks-from openmetrics /in/claude_code_backfill.om /out

echo "3/4  Copying blocks into ${CONTAINER_NAME}:/prometheus ..."
# The prometheus image runs as uid/gid 65534 (nobody). `docker cp` preserves
# the *host* file ownership, so without the chown below Prometheus can scrape
# fine but later fails to compact/delete these blocks ("permission denied"),
# silently wedging ingestion. Every block gets reassigned to nobody:nobody
# right after copying, before Prometheus is restarted to pick them up.
for block in "$BLOCKS_DIR"/*/; do
  block_id="$(basename "$block")"
  docker cp "$block" "${CONTAINER_NAME}:/prometheus/${block_id}"
  docker exec --user root "${CONTAINER_NAME}" chown -R nobody:nobody "/prometheus/${block_id}"
done

echo "4/4  Restarting Prometheus so it picks up the new blocks..."
docker restart "$CONTAINER_NAME" >/dev/null

echo "Done. Give Prometheus ~10s to come back up, then check:"
echo "  curl -s 'http://localhost:9090/api/v1/query?query=claude_code_token_usage_total%7Bsource%3D%22backfill%22%7D' | head -c 500"
echo "Or open Grafana (http://localhost:3001) -> 'Claude Code Agent Workflow' folder and set the source variable to backfill."
