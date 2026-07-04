/** Bounds for a round's submission/voting window, matching the API
 *  (`ge=4, le=168` on `submission_window_hours` / `voting_window_hours`). */
export const MIN_WINDOW_HOURS = 4;
export const MAX_WINDOW_HOURS = 168;

/** Split a total-hours duration into a days + hours pair for display. */
export function hoursToDaysAndHours(totalHours: number): { days: number; hours: number } {
  return { days: Math.floor(totalHours / 24), hours: totalHours % 24 };
}

/** Combine a days + hours pair (as entered in the UI) into total hours. */
export function daysAndHoursToTotal(days: number, hours: number): number {
  return days * 24 + hours;
}

/** Calm, specific validation message for an out-of-range window, or null if
 *  the total is within bounds. The API column and Pydantic field are both
 *  whole hours, so a fractional total (e.g. "3.5" days) must be rejected here
 *  rather than surfacing as a raw 422. */
export function validateWindowHours(totalHours: number): string | null {
  if (!Number.isFinite(totalHours)) return "enter a valid duration.";
  if (!Number.isInteger(totalHours)) return "enter whole days and hours.";
  if (totalHours < MIN_WINDOW_HOURS) return `windows need at least ${MIN_WINDOW_HOURS} hours.`;
  if (totalHours > MAX_WINDOW_HOURS)
    return `windows can't be longer than ${MAX_WINDOW_HOURS} hours (1 week).`;
  return null;
}
