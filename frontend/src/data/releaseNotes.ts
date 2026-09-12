/**
 * The running "what's new" list (MysteryMixClub-*, release-notes modal).
 * Newest first. `date` is both the display title for its group and the
 * uniqueness key `hasUnseenRelease`/`markReleaseSeen` compare against — one
 * entry per release date, hand-maintained alongside the prod release that
 * introduces it. Copy follows the style guide voice: lowercase, short, no
 * exclamation marks, no em dashes.
 */
export type ReleaseNote = {
  /** ISO date (YYYY-MM-DD) of the release this entry describes. */
  date: string;
  items: string[];
};

export const RELEASE_NOTES: ReleaseNote[] = [
  {
    date: "2026-09-12",
    items: [
      "your profile now has a full submission history: every song you've ever submitted, across every club, in a sortable, searchable grid (song, artist, club, mix, date, votes, notes). click a row to see who voted and what people noted, once revealed.",
      "each club now has its own songs page listing every track ever submitted there, once its mystery mix closes, in that same sortable grid.",
    ],
  },
  {
    date: "2026-09-10",
    items: [
      "once more than half the club has submitted or voted in a mystery mix, the mix screen now shows who's still missing so it's easy to give them a nudge.",
    ],
  },
  {
    date: "2026-09-09",
    items: [
      "clubs can now anchor submission and voting deadlines to a fixed day and time every week (say, songs due tuesday at noon, votes due saturday at noon) instead of only a rolling window that starts whenever the previous phase closes. set it from the club settings.",
    ],
  },
];

const STORAGE_KEY = "lastSeenReleaseDate";

/** The most recent entry's date, or undefined if the list is empty. */
export function latestReleaseDate(): string | undefined {
  return RELEASE_NOTES[0]?.date;
}

/**
 * True if there's a release the viewer hasn't dismissed yet. Best-effort:
 * `localStorage` can throw (private browsing, blocked site data) or simply
 * come back empty on a new device — either way this returns a safe default
 * (an unset key reads as "unseen", a thrown read as "don't bother them").
 */
export function hasUnseenRelease(): boolean {
  const latest = latestReleaseDate();
  if (!latest) return false;
  try {
    return localStorage.getItem(STORAGE_KEY) !== latest;
  } catch {
    return false;
  }
}

/** Record the latest release as seen, so the auto-popup doesn't fire again
 *  for it. Safe to call even if reading/writing localStorage throws. */
export function markLatestReleaseSeen(): void {
  const latest = latestReleaseDate();
  if (!latest) return;
  try {
    localStorage.setItem(STORAGE_KEY, latest);
  } catch {
    // Best-effort — worst case the popup reappears next visit.
  }
}

/** "2026-09-09" -> "sep 9, 2026", matching formatDeadline's date style. */
export function formatReleaseDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
    .format(date)
    .toLowerCase();
}
