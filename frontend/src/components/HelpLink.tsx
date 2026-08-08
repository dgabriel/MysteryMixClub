import { Link } from "react-router-dom";

type HelpLinkProps = {
  /** Section id on the help page to deep-link to, e.g. "casual-mode". */
  anchor: string;
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
export function HelpLink({ anchor, className = "" }: HelpLinkProps) {
  return (
    <Link
      to={`/help#${anchor}`}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="what is this?"
      title="what is this?"
      className={[
        "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-hairline font-mono text-label leading-none text-muted-foreground transition-colors duration-150 hover:border-hairline-strong hover:text-foreground",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      ?
    </Link>
  );
}
