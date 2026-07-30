"""Shared helpers for MysteryMixClub Claude Code instrumentation hooks.

Every hook script in this directory imports this module and runs its own
logic through safe_main(). The fail-open contract lives in safe_main(): no
matter what goes wrong (bad JSON on stdin, a missing field, a git call
failing), the hook logs the failure to .instrumentation/events/errors.jsonl
and exits 0. A hook must never block or slow down a Claude Code session.

See scripts/instrumentation/README.md for the full schema reference.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 1


def _repo_root(cwd: str | None) -> Path:
    """Best-effort repo root via a plain `git rev-parse`, not a library.

    Falls back to cwd (or the process cwd) if git isn't available or this
    isn't a git checkout -- never raises.
    """
    run_cwd = cwd or os.getcwd()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=run_cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except Exception:
        pass
    return Path(run_cwd)


def instrumentation_dir(cwd: str | None) -> Path:
    return _repo_root(cwd) / ".instrumentation"


def events_dir(cwd: str | None) -> Path:
    d = instrumentation_dir(cwd) / "events"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_dir(cwd: str | None) -> Path:
    d = instrumentation_dir(cwd) / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append one JSON line. Never rewrites or truncates an existing file."""
    line = json.dumps(record, sort_keys=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def git_branch_and_head(cwd: str | None) -> tuple[str | None, str | None]:
    """Plain `git rev-parse` shell calls, not a library. Returns (None, None)
    fields independently on any failure -- never raises."""
    run_cwd = cwd or os.getcwd()
    branch: str | None = None
    head: str | None = None
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=run_cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            branch = r.stdout.strip() or None
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=run_cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            head = r.stdout.strip() or None
    except Exception:
        pass
    return branch, head


def read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def log_error(cwd: str | None, hook_event_name: str, exc: BaseException) -> None:
    """Write one line to errors.jsonl. Swallows its own failures -- this is
    the fallback path, it has nowhere further to report to."""
    try:
        record = {
            "schema_version": SCHEMA_VERSION,
            "ts": iso_now(),
            "hook_event_name": hook_event_name,
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        append_jsonl(events_dir(cwd) / "errors.jsonl", record)
    except Exception:
        pass


def safe_main(hook_event_name_fallback: str, func: Callable[[dict[str, Any]], None]) -> None:
    """Run func(payload) with the fail-open contract, then exit 0 always.

    func receives the parsed stdin JSON payload. Any exception -- including
    a stdin-parsing failure -- is caught and logged to errors.jsonl, never
    surfaced to the calling Claude Code session and never raised further.
    """
    payload: dict[str, Any] = {}
    try:
        payload = read_stdin_json()
        func(payload)
    except Exception as exc:  # noqa: BLE001 - intentionally broad: fail-open contract
        event_name = payload.get("hook_event_name", hook_event_name_fallback) if payload else hook_event_name_fallback
        cwd = payload.get("cwd") if payload else None
        log_error(cwd, event_name, exc)
    sys.exit(0)
