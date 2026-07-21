import { Link } from "react-router-dom";

type HelpLinkProps = {
  /** Section id on the help page to deep-link to, e.g. "just-vibing". */
  anchor: string;
  className?: string;
};

/**
 * Small "?" affordance linking to a specific /help subsection as inline
 * context help (MYS-222) — for a concept that isn't self-explanatory where it
 * appears (e.g. "just vibing"). Stays in the Sage/Muted/Border family, never
 * Rust — a help icon isn't a screen's primary signal, so it must never spend
 * that screen's one-Rust budget.
 */
export function HelpLink({ anchor, className = "" }: HelpLinkProps) {
  return (
    <Link
      to={`/help#${anchor}`}
      aria-label="what is this?"
      title="what is this?"
      className={[
        "inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-border font-mono text-[10px] leading-none text-muted transition-colors duration-150 hover:border-sage hover:text-sage",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      ?
    </Link>
  );
}
