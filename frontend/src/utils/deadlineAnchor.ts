import type { Weekday } from "../services/api";

/** Weekday options for a weekly-anchor deadline picker (ADR 0021), in
 *  calendar order starting Monday — matching the API's own Monday=0
 *  internal convention, though the wire never speaks in indices. */
export const WEEKDAYS: { value: Weekday; label: string }[] = [
  { value: "monday", label: "monday" },
  { value: "tuesday", label: "tuesday" },
  { value: "wednesday", label: "wednesday" },
  { value: "thursday", label: "thursday" },
  { value: "friday", label: "friday" },
  { value: "saturday", label: "saturday" },
  { value: "sunday", label: "sunday" },
];

// A small curated fallback for browsers without Intl.supportedValuesOf
// (Safari < 15.4, older engines). Not exhaustive — just enough that a picker
// still works everywhere; the modern path below covers the full IANA set.
const FALLBACK_TIMEZONES = [
  "UTC",
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Sao_Paulo",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Moscow",
  "Africa/Johannesburg",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Shanghai",
  "Asia/Tokyo",
  "Australia/Sydney",
  "Pacific/Auckland",
];

/** Every IANA zone name the runtime knows about, or the curated fallback list
 *  above on an engine that doesn't support `Intl.supportedValuesOf` yet. */
export function listTimezones(): string[] {
  const supportedValuesOf = (
    Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  ).supportedValuesOf;
  if (typeof supportedValuesOf === "function") {
    try {
      return supportedValuesOf("timeZone");
    } catch {
      // Fall through to the curated list below.
    }
  }
  return FALLBACK_TIMEZONES;
}

/** The viewer's own timezone, as a sensible default for a new weekly-anchor
 *  schedule — most organizers configuring one live in the zone they want it
 *  to run in. */
export function detectTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "UTC";
  }
}

/** Calm, specific validation message for an incomplete weekly-anchor phase
 *  (both a day and a time are required together), or null if it's complete.
 *  Shared between club creation and the post-creation settings edit. */
export function validateAnchor(
  weekday: Weekday | "",
  time: string,
  label: "submission" | "voting",
): string | null {
  if (!weekday || !time) return `choose a day and time for the ${label} deadline.`;
  return null;
}

/** The API returns a phase time as "HH:MM:SS"; `<input type="time">` wants
 *  "HH:MM". Null (no schedule set yet) becomes "". */
export function toTimeInputValue(apiTime: string | null): string {
  return apiTime ? apiTime.slice(0, 5) : "";
}
