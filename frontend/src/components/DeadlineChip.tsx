import type { Round } from "../services/api";
import { formatDeadline } from "../utils/deadline";
import { ClockIcon } from "./ClockIcon";

/**
 * Phase-appropriate deadline chip (MYS-161). Renders the shared formatDeadline()
 * label as the style guide's "Time signal (Ink)" chip — Ink fill, Cream text,
 * with an inline clock icon — reserved for time-critical info (one per screen).
 * Renders nothing at all for legacy rounds (null deadline) or non-open states —
 * the helper returns null there. `className` carries the per-page top margin so
 * spacing fits each layout; the chip itself is identical on every screen.
 */
export function DeadlineChip({ round, className }: { round: Round; className?: string }) {
  const label = formatDeadline(round);
  if (!label) return null;
  return (
    <div className={className}>
      <span className="inline-flex items-center gap-1.5 rounded-[1px] bg-ink px-[10px] py-[4px] font-mono uppercase tracking-ui text-[11px] text-cream">
        <ClockIcon />
        {label}
      </span>
    </div>
  );
}
