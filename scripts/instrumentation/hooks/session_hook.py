#!/usr/bin/env python3
"""Claude Code hook: SessionStart / SessionEnd -> .instrumentation/events/sessions.jsonl

Registered in .claude/settings.json under both SessionStart and SessionEnd.
Fail-open: any error here is logged to events/errors.jsonl; this script
always exits 0 (see scripts/instrumentation/README.md).

On SessionStart, also drops the session id into
.instrumentation/state/current_session so other tooling in this same
session (e.g. the reviewer subagent's review-logging helper, Phase 3) can
find it without guessing at an undocumented env var.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    SCHEMA_VERSION,
    append_jsonl,
    events_dir,
    git_branch_and_head,
    instrumentation_dir,
    iso_now,
    safe_main,
)


def _write_current_session_pointer(cwd: str | None, session_id: str | None) -> None:
    if not session_id:
        return
    state = instrumentation_dir(cwd) / "state"
    state.mkdir(parents=True, exist_ok=True)
    pointer = state / "current_session"
    tmp = pointer.with_suffix(".tmp")
    tmp.write_text(session_id, encoding="utf-8")
    tmp.replace(pointer)  # atomic on POSIX


def main(payload: dict) -> None:
    cwd = payload.get("cwd")
    session_id = payload.get("session_id")
    hook_event_name = payload.get("hook_event_name", "SessionStart")
    branch, head = git_branch_and_head(cwd)

    record = {
        "schema_version": SCHEMA_VERSION,
        "ts": iso_now(),
        "event_type": hook_event_name,
        "session_id": session_id,
        "cwd": cwd,
        "git_branch": branch,
        "git_head": head,
        # "reason" is a confirmed *matcher* value for SessionEnd (clear /
        # resume / logout / prompt_input_exit / bypass_permissions_disabled
        # / other) as of Claude Code 2.1.220, but not confirmed as an actual
        # payload field -- only ever taken from a real field if present,
        # never guessed. Stays null otherwise.
        "reason": payload.get("reason"),
    }
    append_jsonl(events_dir(cwd) / "sessions.jsonl", record)

    if hook_event_name == "SessionStart":
        _write_current_session_pointer(cwd, session_id)


if __name__ == "__main__":
    safe_main("SessionStart", main)
