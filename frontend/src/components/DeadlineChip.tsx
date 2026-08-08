import { useEffect, useRef, useState } from "react";
import type { Mix } from "../services/api";
import { formatCountdown, formatDeadline } from "../utils/deadline";
import { ClockIcon } from "./ClockIcon";

/**
 * Phase-appropriate deadline chip (MYS-161). Renders the shared formatDeadline()
 * label in a chip with an inline clock icon.
 *
 * The retired system's dark-filled "time signal" chip worked by contrast
 * inversion — the densest object on a light page. On a near-black page a dark
 * fill inverts nothing, so there is no direct analogue and this chip is graded
 * by urgency instead: a neutral `tile` chip for a plain date, and the amber
 * callout treatment only once the deadline is actually closing. That keeps
 * amber inside its category ("closing soon" is an action prompt; "closes jul 5"
 * is a date) and gives sighted users the urgency cue that until now only the
 * aria-live announcement carried.
 *
 * Renders nothing at all for legacy mixes (null deadline) or non-open states —
 * the helper returns null there. `className` carries the per-page top margin so
 * spacing fits each layout; the chip itself is identical on every screen.
 *
 * `showCountdown` opts into the live "2d 14h remaining" / "closing soon…" half
 * of the chip (mix detail page only, per the ticket — the club page's
 * per-mix cards stay static so a list of mixes doesn't tick). A 1-minute
 * interval keeps it live without a page refresh; cleared on unmount.
 */
export function DeadlineChip({
  mix,
  className,
  showCountdown = false,
}: {
  mix: Mix;
  className?: string;
  showCountdown?: boolean;
}) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    if (!showCountdown) return;
    const interval = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(interval);
  }, [showCountdown]);

  const label = formatDeadline(mix);
  const countdown = showCountdown ? formatCountdown(mix, now) : null;
  const closingSoon = countdown === "closing soon…";
  const wasClosingSoon = useRef(false);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    if (closingSoon && !wasClosingSoon.current) {
      setAnnouncement("this mystery mix is closing soon");
    }
    wasClosingSoon.current = closingSoon;
  }, [closingSoon]);

  if (!label) return null;

  return (
    <div className={className}>
      <span
        className={[
          "inline-flex items-center gap-1.5 rounded-hair border px-2 py-1 font-mono uppercase tracking-mono text-label",
          // Neutral text is `foreground`, not `muted-foreground`, so a time
          // signal still outranks a `Badge` status word — that hierarchy is
          // what survives from the old Ink fill's prominence.
          closingSoon
            ? "bg-accent-surface border-accent-hairline text-accent"
            : "bg-tile border-hairline text-foreground",
        ].join(" ")}
      >
        <ClockIcon />
        {countdown ? `${label} · ${countdown}` : label}
      </span>
      {showCountdown ? (
        <p role="status" aria-live="polite" className="sr-only">
          {announcement}
        </p>
      ) : null}
    </div>
  );
}
