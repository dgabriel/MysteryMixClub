"""Computes a mix phase's deadline from its club's deadline configuration (ADR 0021).

A club is in one of two deadline modes: "duration" (the long-standing MYS-159
behavior — `submission_window_hours`/`voting_window_hours` counted from
whenever the phase opens) or "weekly_anchor" (a fixed weekday + time, in the
club's chosen IANA timezone, for both phases together). This module is the
single place that branches on `club.deadline_mode`; every phase-deadline stamp
in the mix lifecycle (`advance_mix_state`'s three stamps,
`rollback_mix_to_submission`, and `advance_mixes.py`'s Branch 1) calls
`compute_phase_deadline()` instead of re-deriving the arithmetic inline.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from app.models.club import Club

Phase = Literal["submission", "voting"]

# If the raw "next occurrence" of a weekly anchor would land less than this far
# in the future, roll to the following week instead — a phase that happens to
# open just before its anchor time (or after it, same day) should never get a
# near-zero window.
MIN_ANCHOR_LEAD = timedelta(hours=24)


def compute_phase_deadline(club: Club, phase: Phase, now: datetime) -> datetime:
    """The deadline for ``phase`` opening on ``club`` right now, in UTC."""
    if club.deadline_mode == "weekly_anchor":
        weekday = club.submission_weekday if phase == "submission" else club.voting_weekday
        at_time = club.submission_time if phase == "submission" else club.voting_time
        if weekday is None or at_time is None:
            raise ValueError(
                f"club {club.id} is in weekly_anchor mode but has no {phase} schedule set"
            )
        return _next_weekly_occurrence(now, club.timezone, weekday, at_time)

    window_hours = (
        club.submission_window_hours if phase == "submission" else club.voting_window_hours
    )
    return now + timedelta(hours=window_hours)


def _next_weekly_occurrence(now: datetime, tz_name: str, weekday: int, at_time: time) -> datetime:
    """The next UTC instant a wall-clock ``weekday``/``at_time`` occurs in
    ``tz_name``, at least :data:`MIN_ANCHOR_LEAD` after ``now``.

    ``weekday`` follows ``date.weekday()`` (Monday=0..Sunday=6). DST handling
    is whatever `zoneinfo` resolves by default for an ambiguous/skipped local
    time at a transition boundary (PEP 495 `fold=0`) — not bespoke
    disambiguation logic (see ADR 0021).
    """
    zone = ZoneInfo(tz_name)
    local_now = now.astimezone(zone)
    days_ahead = (weekday - local_now.weekday()) % 7
    candidate = datetime.combine(
        local_now.date() + timedelta(days=days_ahead), at_time, tzinfo=zone
    )
    if candidate - local_now < MIN_ANCHOR_LEAD:
        candidate += timedelta(days=7)
    return candidate.astimezone(timezone.utc)
