"""When the push-only nudges are due (MysteryMixClub-bfqo).

Pure time arithmetic, kept apart from the job so every rule can be tested with
plain datetimes. Two of the three nudges are pinned to a moment (the "last few"
one is state-driven and lives in the job):

* **halfway** -- the midpoint between a phase opening and its deadline.
* **due morning** -- 08:00 on the local calendar day the phase is due, in the
  club's timezone (or :data:`DEFAULT_DUE_MORNING_TZ` for a club with none).

Both are measured from the phase's real stamps (``*_opened_at`` and the
deadline), not from the club's configured window: a weekly-anchor club's window
is whatever the calendar gives it (ADR 0021), and an organizer can extend a
deadline.

The deadline job runs every 15 minutes, so a nudge lands within about 15
minutes after its moment. A nudge whose moment passed more than
:data:`NUDGE_GRACE` ago is dropped rather than sent late (a job outage, or the
first run after a deploy, must not announce "halfway" hours after the fact).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NUDGE_GRACE = timedelta(hours=1)
# A phase shorter than this has no halfway worth announcing.
NUDGE_MIN_WINDOW = timedelta(hours=6)
# The due-morning nudge goes out at this local hour, and only when it leaves at
# least this long before the deadline (an 8:10am deadline gets no "due today").
DUE_MORNING_HOUR = 8
DUE_MORNING_MIN_LEAD = timedelta(hours=1)
# A club with no chosen timezone (every duration-mode club: its stored timezone
# is the "UTC" placeholder) gets the due-today nudge at 8am US Central instead
# (Dawn's call, MysteryMixClub-sqhj). America/Chicago rather than a fixed UTC-6
# so it stays 8am on the wall clock through daylight saving.
DEFAULT_DUE_MORNING_TZ = "America/Chicago"
# Two pushes to the same audience closer together than this are one push too
# many: only the more established one is sent (see :func:`near_any`).
COINCIDENCE = timedelta(hours=1)

# The existing reminders' own lead times and the minimum club window each one
# needs (advance_mixes.py). Repeated here as the moments they land, to detect
# a nudge falling on top of one.
_WARNING_LEAD = timedelta(hours=12)
_WARNING_MIN_WINDOW_HOURS = 12
_FAR_REMINDER_LEAD = timedelta(hours=24)
# The job's ~24h band is 23-24h before the deadline (advance_mixes.py).
_FAR_REMINDER_MIN_LEAD = timedelta(hours=23)
_FAR_REMINDER_MIN_WINDOW_HOURS = 24


def halfway_at(opened_at: datetime, deadline: datetime) -> datetime | None:
    """Midpoint of the phase, or None when the phase is too short to bother."""
    window = deadline - opened_at
    if window < NUDGE_MIN_WINDOW:
        return None
    return opened_at + window / 2


def due_morning_at(opened_at: datetime, deadline: datetime, tz_name: str) -> datetime | None:
    """08:00 on the ``tz_name`` calendar day of ``deadline``, as a UTC instant.

    None when that moment is not after the phase opened (it opened later that
    morning, so the player has only just heard about it) or leaves less than
    :data:`DUE_MORNING_MIN_LEAD` before the deadline, or when the timezone name
    is unknown (one bad club row must not silence the club's other nudges)."""
    try:
        zone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
    local_day = deadline.astimezone(zone).date()
    at = datetime.combine(local_day, time(DUE_MORNING_HOUR), tzinfo=zone).astimezone(timezone.utc)
    if at <= opened_at or at > deadline - DUE_MORNING_MIN_LEAD:
        return None
    return at


def scheduled_reminder_times(
    opened_at: datetime, deadline: datetime, window_hours: int
) -> list[datetime]:
    """The moments the existing deadline reminders (12h warning, ~24h push) land
    for a phase, by the same club-window gate the job applies to them.

    The job fires each one at the first pass inside its band, so a phase that is
    shorter than the reminder's lead (weekly-anchor and organizer-set deadlines
    can make it so) gets it as soon as the phase opens: the moment is clamped to
    ``opened_at``. The ~24h push needs a band of 23-24h to exist at all."""
    times: list[datetime] = []
    if window_hours > _WARNING_MIN_WINDOW_HOURS:
        times.append(max(deadline - _WARNING_LEAD, opened_at))
    if window_hours > _FAR_REMINDER_MIN_WINDOW_HOURS and (
        deadline - opened_at >= _FAR_REMINDER_MIN_LEAD
    ):
        times.append(max(deadline - _FAR_REMINDER_LEAD, opened_at))
    return times


def near_any(moment: datetime, others: list[datetime]) -> bool:
    return any(abs(moment - other) < COINCIDENCE for other in others)


def is_due(moment: datetime, now: datetime) -> bool:
    """True from ``moment`` until :data:`NUDGE_GRACE` after it."""
    return moment <= now < moment + NUDGE_GRACE
