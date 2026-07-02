import type { Round } from "../services/api";

/**
 * Static, phase-appropriate deadline label for a round, formatted in the
 * viewer's browser-local timezone (MYS-161). Returns the submission deadline
 * while a round is `open_submission` and the voting deadline while
 * `open_voting`; any other state — or a null deadline (legacy rounds) — yields
 * null so callers render nothing at all.
 *
 * Copy style follows the style guide voice: short, lowercase, calm —
 * e.g. `closes jul 5 at 9:00 pm`. Formatting is delegated to Intl so the time
 * lands in the viewer's own timezone with no hand-rolled offset math.
 */
export function formatDeadline(round: Round): string | null {
  const iso =
    round.state === "open_submission"
      ? round.submission_deadline
      : round.state === "open_voting"
        ? round.voting_deadline
        : null;
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
