import { Link } from "react-router";

type HelpLinkProps = {
  /** Section id on the help page to deep-link to, e.g. "casual-mode". */
  anchor: string;
  /** The link is on the light page surface (`paper`, ADR 0013) rather than
   *  inside a dark card.
   *
   *  It genuinely renders on both: `/home` puts two of these directly on the
   *  page, while `SongSearchCard` renders one inside its own `bg-card`. So this
   *  cannot be converted outright — the card-bound instances must keep the dark
   *  ramp. The glyph is what satisfies WCAG 1.4.11 (the ring is ~1.2:1 either
   *  way), so it is the part that has to clear on whichever surface it lands. */
  onPaper?: boolean;
  className?: string;
};

/**
 * Small "?" affordance linking to a specific /help subsection as inline
 * context help (MYS-222) — for a concept that isn't self-explanatory where it
 * appears (e.g. "casual mode"). Deliberately not amber, even on hover: a help
 * affordance is never the screen's signal, and MyClubsScreen renders two of
 * them, which would be amber as pattern. Hover brightens within the neutral
 * ramp instead.
 *
 * The circle is a `hairline` at ~1.2:1, so the "?" glyph is what satisfies
 * WCAG 1.4.11 (`muted-foreground`, 6.01:1 on `card`). Do not drop the glyph to
 * a fainter ramp step.
 *
 * Opens in a new tab: several of these sit on forms with in-progress input
 * (e.g. creating a club) that a same-tab navigation away would lose.
 */
export function HelpLink({ anchor, onPaper = false, className = "" }: HelpLinkProps) {
  return (
    <Link
      to={`/help#${anchor}`}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="what is this?"
      title="what is this?"
      className={[
        "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border font-mono text-label leading-none transition-colors duration-150",
        onPaper
          ? "border-ink-hairline text-ink-muted hover:border-ink hover:text-ink"
          : "border-hairline text-muted-foreground hover:border-hairline-strong hover:text-foreground",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      ?
    </Link>
  );
}
