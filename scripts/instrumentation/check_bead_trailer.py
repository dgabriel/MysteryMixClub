#!/usr/bin/env python3
"""Require a `Bead: <id>` trailer on commit messages so git history and the
bd issue graph can be joined exactly (Phase 2, MysteryMixClub-ghal).

Called from the commit-msg git hook (.beads/hooks/commit-msg and
.husky/commit-msg, kept in sync), after commitlint has already validated
Conventional Commit formatting. This script only checks the Bead trailer;
it does not re-validate the commit type/format.

Bypass: commits whose Conventional Commit type is chore/docs/ci/style/build/
revert, or any merge commit, don't need a Bead trailer. Documented here and
in AGENTS.md / CLAUDE.md.

Exit 1 (blocks the commit) when a trailer is required and missing/invalid.
Exit 0 otherwise. This hook is allowed to block -- unlike the Claude Code
session/subagent hooks in scripts/instrumentation/hooks/, which must always
fail open. A git commit-msg hook failing loudly and a Claude Code hook
silently swallowing errors are different failure domains on purpose.

This script makes ZERO writes to the bd issue graph -- `bd show` (read-only)
is the only bd command it ever runs.
"""
import re
import subprocess
import sys

BYPASS_TYPES = {"chore", "docs", "ci", "style", "build", "revert"}
CONVENTIONAL_HEADER_RE = re.compile(r"^(?P<type>\w+)(\([^)]*\))?!?:\s")
TRAILER_RE = re.compile(r"^Bead:\s*(\S+)\s*$")


def _bd_prefix() -> str | None:
    try:
        r = subprocess.run(
            ["bd", "where", "--json"], capture_output=True, text=True, timeout=5
        )
        if r.returncode != 0:
            return None
        import json

        return json.loads(r.stdout).get("prefix")
    except Exception:
        return None


def _bd_issue_exists(issue_id: str) -> bool | None:
    """True/False if bd can answer, None if bd itself is unavailable
    (infra problem, not an invalid-id problem -- don't block on that)."""
    try:
        r = subprocess.run(
            ["bd", "show", issue_id], capture_output=True, text=True, timeout=10
        )
    except Exception:
        return None
    if r.returncode == 0:
        return True
    # bd prints a clear "not found" style message on a bad id; treat any
    # non-zero exit as "doesn't exist" only if bd actually ran (no exception
    # above). A crashed/missing bd binary would have raised already.
    return False


def main() -> int:
    if len(sys.argv) < 2:
        # Called wrong -- don't block a commit over our own misuse.
        return 0

    msg_path = sys.argv[1]
    try:
        with open(msg_path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return 0

    # Strip comment lines (git includes "# ..." guidance in the edited file).
    content_lines = [ln for ln in lines if not ln.startswith("#")]
    if not content_lines or not content_lines[0].strip():
        return 0  # empty message; commitlint already handles that failure

    header = content_lines[0].strip()

    if header.startswith("Merge "):
        return 0  # merge commits are exempt

    m = CONVENTIONAL_HEADER_RE.match(header)
    commit_type = m.group("type").lower() if m else None
    if commit_type in BYPASS_TYPES:
        return 0

    trailer_value = None
    for line in content_lines:
        tm = TRAILER_RE.match(line.strip())
        if tm:
            trailer_value = tm.group(1)
            break

    if trailer_value is None:
        sys.stderr.write(
            "\ncommit-msg: missing required 'Bead: <id>' trailer.\n"
            "Every non-chore/docs/ci/style/build/revert commit must reference the\n"
            "bd issue it belongs to, e.g.:\n\n"
            "    Bead: MysteryMixClub-abc123\n\n"
            "Start work with scripts/bead-start.sh <issue-id> so the branch and the\n"
            "claim are set up together, then this trailer is just the id it gave you.\n"
            "Bypass types (no trailer needed): "
            + ", ".join(sorted(BYPASS_TYPES))
            + ".\n\n"
        )
        return 1

    prefix = _bd_prefix()
    id_shape_ok = True
    if prefix:
        id_shape_ok = bool(re.match(rf"^{re.escape(prefix)}-[A-Za-z0-9]+(\.[0-9]+)?$", trailer_value))

    if not id_shape_ok:
        sys.stderr.write(
            f"\ncommit-msg: 'Bead: {trailer_value}' doesn't look like a {prefix} issue id.\n\n"
        )
        return 1

    exists = _bd_issue_exists(trailer_value)
    if exists is False:
        sys.stderr.write(
            f"\ncommit-msg: 'Bead: {trailer_value}' -- no such issue in bd (bd show found nothing).\n"
            "Check the id, or create the issue first with bd create.\n\n"
        )
        return 1
    # exists is None -> bd itself unavailable; don't block on an infra gap,
    # the format check above already ran.

    return 0


if __name__ == "__main__":
    sys.exit(main())
