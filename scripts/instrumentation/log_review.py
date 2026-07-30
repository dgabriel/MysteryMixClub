#!/usr/bin/env python3
"""Append one review-verdict record to .instrumentation/events/reviews.jsonl.

Called by the reviewer subagent (.claude/agents/reviewer.md) via its own
Bash tool at the end of every review pass. This is a normal script the
reviewer invokes deliberately -- unlike scripts/instrumentation/hooks/*.py,
it does NOT need to fail open. A logging failure here should be visible
(printed to stderr, non-zero exit) so it shows up in the reviewer's own
transcript, rather than silently vanishing the way a Claude Code hook
failure is designed to.

Usage:
  scripts/instrumentation/log_review.py <issue_id> <PASS|FAIL> <reason_code>

reason_code is a closed vocabulary (see REASON_CODES) on purpose -- this is
the rework signal for the eval framework later, and free text doesn't
aggregate.

iteration_number is per issue, not per session: it's 1 + the count of prior
records in reviews.jsonl for the same issue_id, so re-reviewing the same
issue across multiple sessions (rework) still counts correctly.

session_id is read from .instrumentation/state/current_session, written by
the SessionStart hook (scripts/instrumentation/hooks/session_hook.py) --
subagent invocations share their parent session's session_id, confirmed
against Claude Code 2.1.220's hook payload docs. If that pointer file is
missing (hooks not installed, or logging this from outside a live Claude
Code session), session_id is null rather than guessed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "hooks"))
from _common import SCHEMA_VERSION, append_jsonl, events_dir, instrumentation_dir, iso_now  # noqa: E402

VERDICTS = {"PASS", "FAIL"}

# Closed vocabulary, mapped to the categories in .claude/agents/reviewer.md.
# When a FAIL spans more than one category, use the first of these that
# applies (severity order, most severe first).
REASON_CODES = [
    "security_issue",   # secrets/auth/input-validation problem
    "logic_defect",     # doesn't match the issue, or an unhandled edge case
    "scope_mismatch",   # doesn't match what the issue asked for / unjustified scope creep
    "quality_issue",    # placeholder logic, TODOs, unclear naming/typing, unjustified complexity
    "style_violation",  # design-system non-compliance (color/font/input style)
    "clean",            # PASS only: nothing found
]
REASON_CODE_SET = set(REASON_CODES)


def main() -> int:
    if len(sys.argv) != 4:
        sys.stderr.write(
            "Usage: scripts/instrumentation/log_review.py <issue_id> <PASS|FAIL> <reason_code>\n"
            f"reason_code must be one of: {', '.join(REASON_CODES)}\n"
        )
        return 1

    issue_id, verdict, reason_code = sys.argv[1], sys.argv[2], sys.argv[3]

    if verdict not in VERDICTS:
        sys.stderr.write(f"error: verdict must be PASS or FAIL, got {verdict!r}\n")
        return 1
    if reason_code not in REASON_CODE_SET:
        sys.stderr.write(f"error: reason_code {reason_code!r} not in closed vocabulary: {', '.join(REASON_CODES)}\n")
        return 1
    if verdict == "PASS" and reason_code != "clean":
        sys.stderr.write("error: a PASS verdict must use reason_code 'clean'\n")
        return 1
    if verdict == "FAIL" and reason_code == "clean":
        sys.stderr.write("error: a FAIL verdict cannot use reason_code 'clean'\n")
        return 1

    cwd = str(Path.cwd())
    reviews_path = events_dir(cwd) / "reviews.jsonl"
    iteration_number = _next_iteration_number(reviews_path, issue_id)
    session_id = _current_session_id(cwd)

    record = {
        "schema_version": SCHEMA_VERSION,
        "ts": iso_now(),
        "issue_id": issue_id,
        "session_id": session_id,
        "iteration_number": iteration_number,
        "verdict": verdict,
        # Not derivable from any stored raw event today -- no hook or tool
        # call exposes which model the reviewer subagent runs under. Left
        # null rather than guessed; see scripts/instrumentation/README.md.
        "model": None,
        "reason_code": reason_code,
    }
    append_jsonl(reviews_path, record)
    print(f"Logged review #{iteration_number} for {issue_id}: {verdict} ({reason_code})")
    return 0


def _current_session_id(cwd: str) -> str | None:
    pointer = instrumentation_dir(cwd) / "state" / "current_session"
    if pointer.exists():
        val = pointer.read_text(encoding="utf-8").strip()
        return val or None
    return None


def _next_iteration_number(reviews_path: Path, issue_id: str) -> int:
    if not reviews_path.exists():
        return 1
    count = 0
    with open(reviews_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("issue_id") == issue_id:
                count += 1
    return count + 1


if __name__ == "__main__":
    sys.exit(main())
