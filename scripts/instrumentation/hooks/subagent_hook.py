#!/usr/bin/env python3
"""Claude Code hook: SubagentStart / SubagentStop -> .instrumentation/events/agents.jsonl

Registered in .claude/settings.json under both SubagentStart and
SubagentStop. Fail-open: any error here is logged to events/errors.jsonl;
this script always exits 0 (see scripts/instrumentation/README.md).

Verified against Claude Code 2.1.220's own docs (code.claude.com/docs/en/
hooks.md, checked 2026-07-29): SubagentStart/SubagentStop payloads carry
agent_id (unique per invocation) and agent_type (the subagent's frontmatter
`name`, e.g. "developer"/"tester"/"reviewer"/"ui-agent"), but no model
identifier, token counts, or duration. duration_ms is derived here instead,
by pairing this Start event's own hook-fire timestamp with the matching
Stop event's, keyed on agent_id -- both timestamps are raw events this
script itself observes and stores, not a substitution for anything absent.
model/input_tokens/output_tokens are left null: confirmed unavailable from
any Claude Code hook payload today (see README "What this cannot measure").
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    SCHEMA_VERSION,
    append_jsonl,
    events_dir,
    iso_now,
    safe_main,
    state_dir,
)


def _start_marker_path(cwd: str | None, agent_id: str) -> Path:
    return state_dir(cwd) / f"agent_{agent_id}.start"


def _handle_start(cwd: str | None, agent_id: str | None, ts: str) -> None:
    if not agent_id:
        return
    marker = _start_marker_path(cwd, agent_id)
    tmp = marker.with_suffix(".tmp")
    tmp.write_text(ts, encoding="utf-8")
    tmp.replace(marker)  # atomic on POSIX


def _handle_stop(cwd: str | None, agent_id: str | None, stop_ts_iso: str) -> int | None:
    """Returns duration_ms, or None if no matching Start marker exists.

    A missing marker (hook added mid-session, marker file lost, etc.) means
    genuinely missing data -- emit null, never substitute another timestamp.
    """
    if not agent_id:
        return None
    marker = _start_marker_path(cwd, agent_id)
    if not marker.exists():
        return None
    duration_ms: int | None
    try:
        start_ts = datetime.fromisoformat(marker.read_text(encoding="utf-8").strip())
        stop_ts = datetime.fromisoformat(stop_ts_iso)
        duration_ms = int((stop_ts - start_ts).total_seconds() * 1000)
    except Exception:
        duration_ms = None
    finally:
        try:
            marker.unlink()
        except OSError:
            pass
    return duration_ms


def main(payload: dict) -> None:
    cwd = payload.get("cwd")
    session_id = payload.get("session_id")
    agent_id = payload.get("agent_id")
    agent_type = payload.get("agent_type")
    hook_event_name = payload.get("hook_event_name", "SubagentStart")
    ts = iso_now()

    duration_ms = None
    exit_status = None
    if hook_event_name == "SubagentStart":
        _handle_start(cwd, agent_id, ts)
    elif hook_event_name == "SubagentStop":
        duration_ms = _handle_stop(cwd, agent_id, ts)
        # No field documenting how/why a subagent stopped is confirmed to
        # exist on this payload as of Claude Code 2.1.220. Only ever taken
        # from a real field if one shows up at runtime -- never fabricated.
        exit_status = payload.get("stop_reason")

    record = {
        "schema_version": SCHEMA_VERSION,
        "ts": ts,
        "event_type": hook_event_name,
        "session_id": session_id,
        "agent_id": agent_id,
        "subagent_name": agent_type,
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
        "duration_ms": duration_ms,
        "exit_status": exit_status,
    }
    append_jsonl(events_dir(cwd) / "agents.jsonl", record)


if __name__ == "__main__":
    safe_main("SubagentStart", main)
