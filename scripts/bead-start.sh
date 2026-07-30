#!/usr/bin/env bash
#
# MysteryMixClub — the single entry point for starting work on a bd issue.
#
# Usage: scripts/bead-start.sh <bd-issue-id>
#
# What it does, in order:
#   1. Refuses to run on a dirty working tree (docs/git-hygiene.md).
#   2. Looks up the issue in bd (read-only) for its title and type.
#   3. Syncs `develop` and branches off it: feature/<id>-<slug>, or
#      fix/<id>-<slug> for a bug (docs/git-hygiene.md: every branch is based
#      off an up-to-date develop, never off main or a stacked branch).
#      Re-running this for a branch that already exists just switches to it.
#   4. Only once the branch exists: `bd update <id> --claim`.
#
# This is the ONLY place in the instrumentation work (MysteryMixClub-ghal)
# that writes to the bd issue graph, and `--claim` is the only bd write it
# ever makes. The commit-msg hook (scripts/instrumentation/check_bead_trailer.py)
# then requires every commit on the branch to carry `Bead: <id>` so git
# history and the bd issue graph join exactly.
#
# See AGENTS.md / CLAUDE.md for why this script, not manual branch/claim
# steps, is expected for starting work.

set -euo pipefail

usage() {
  echo "Usage: scripts/bead-start.sh <bd-issue-id>" >&2
  exit 1
}

[ $# -eq 1 ] || usage
ISSUE_ID="$1"

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if [ -n "$(git status --porcelain)" ]; then
  echo "error: working tree is not clean. Commit, stash, or discard first." >&2
  git status --short >&2
  exit 1
fi

ISSUE_JSON="$(bd show "$ISSUE_ID" --json 2>/dev/null)" || {
  echo "error: bd has no issue '$ISSUE_ID' (bd show failed)." >&2
  exit 1
}

TITLE="$(echo "$ISSUE_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["title"])')"
ISSUE_TYPE="$(echo "$ISSUE_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["issue_type"])')"

if [ "$ISSUE_TYPE" = "bug" ]; then
  PREFIX="fix"
else
  PREFIX="feature"
fi

SLUG="$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' | cut -c1-50)"
BRANCH="${PREFIX}/${ISSUE_ID}-${SLUG}"

git fetch --prune origin
git checkout develop
git pull --ff-only origin develop

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "Branch '$BRANCH' already exists -- switching to it (resuming)."
  git checkout "$BRANCH"
else
  git checkout -b "$BRANCH"
fi

bd update "$ISSUE_ID" --claim

echo
echo "Branch '$BRANCH' ready, $ISSUE_ID claimed."
echo "Every commit on this branch needs a trailer: Bead: $ISSUE_ID"
