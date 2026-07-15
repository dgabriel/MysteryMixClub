import type { Round } from "../services/api";

/** The deadline ISO string for a round's current phase — submission deadline
 *  while `open_submission`, voting deadline while `open_voting`, null in any
 *  other state (or if that phase's deadline was never stamped — legacy
 *  rounds). Shared by formatDeadline and formatCountdown so both always agree
 *  on which deadline is "the" deadline. */
function activeDeadlineIso(round: Round): string | null {
  return round.state === "open_submission"
    ? round.submission_deadline
    : round.state === "open_voting"
      ? round.voting_deadline
      : null;
}

/**
 * Static, phase-appropriate deadline label for a round, formatted in the
 * viewer's browser-local timezone (MYS-161). Returns null for a round with no
 * active-phase deadline so callers render nothing at all.
 *
 * Copy style follows the style guide voice: short, lowercase, calm —
 * e.g. `closes jul 5 at 9:00 pm`. Formatting is delegated to Intl so the time
 * lands in the viewer's own timezone with no hand-rolled offset math.
 */
export function formatDeadline(round: Round): string | null {
  const iso = activeDeadlineIso(round);
  if (!iso) return null;

  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;

  const day = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(date);
  const time = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(date);

  return `closes ${day} at ${time}`.toLowerCase();
}

/**
 * Live "time remaining" label for a round's current phase (MYS-161):
 * "2d 14h remaining" once at least a day remains, "3h 12m remaining" under a
 * day (so a short window — e.g. a 4h league setting — never reads as
 * "0d 3h"), and "closing soon…" once the deadline has passed but the round
 * hasn't been force-advanced yet. Returns null under the same conditions as
 * formatDeadline (no active-phase deadline, or an unparseable one).
 *
 * `now` is injectable so tests don't depend on wall-clock time; callers
 * re-invoke this on an interval to keep the label live.
 */
export function formatCountdown(round: Round, now: Date = new Date()): string | null {
  const iso = activeDeadlineIso(round);
  if (!iso) return null;

  const deadline = new Date(iso);
  if (Number.isNaN(deadline.getTime())) return null;

  const diffMs = deadline.getTime() - now.getTime();
  if (diffMs <= 0) return "closing soon…";

  const totalMinutes = Math.floor(diffMs / 60_000);
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  const minutes = totalMinutes % 60;

  return days > 0 ? `${days}d ${hours}h remaining` : `${hours}h ${minutes}m remaining`;
}

/**
 * Format a Date as the local "YYYY-MM-DDTHH:mm" string an
 * `<input type="datetime-local">` needs for its `value`/`min`/`max` (MYS-180).
 * Local time, no timezone conversion — the input (and `new Date()` parsing that
 * same shape back) both operate in the browser's local zone, so this round-trips.
 */
export function toDatetimeLocalValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  const y = date.getFullYear();
  const m = pad(date.getMonth() + 1);
  const d = pad(date.getDate());
  const h = pad(date.getHours());
  const min = pad(date.getMinutes());
  return `${y}-${m}-${d}T${h}:${min}`;
}
