import type { ReactNode } from "react";
import { ConcentricRings } from "./ConcentricRings";

type BrandLockupProps = {
  /**
   * Element the wordmark renders as.
   *
   * `"h1"` **only** on a screen that has no title of its own — the sign-in
   * screen, where "mysterymixclub" genuinely is the page's heading.
   *
   * `"p"` (the default) everywhere else. Those pages already have an `h1`
   * (`about`, `terms of service`, …), and a second one would both break the
   * heading outline and demote the page's actual subject beneath the site name.
   * The wordmark stays visually dominant either way — size and semantics are
   * independent, and this prop is the seam between them.
   */
  as?: "h1" | "p";
  /** Rendered under the wordmark, inside the same centred block — the sign-in
   *  screen's `beta` badge. Other pages get that badge from `TopNav`. */
  children?: ReactNode;
  className?: string;
};

/**
 * The brand lockup: the spinning disc beside the two-line wordmark, in the
 * design system's own hero arrangement (DS `App.tsx:427-437`) — a row that
 * stacks to a column below `sm`, exactly as the DS's `flex-col sm:flex-row`
 * does.
 *
 * The wordmark clamps at 3.5rem rather than the DS's 5.5rem, and the row uses a
 * 28px gap rather than 32px. The DS sets this hero beside a 96px disc in a 72rem
 * page; ours has to fit a 24rem (sign-in) or 28rem (public pages) column, and at
 * 4.5rem the disc + gap + wordmark came to 344px inside 352px of usable width —
 * technically fitting, visibly cramped.
 *
 * Deliberately NOT `aria-hidden`. `TopNav`'s 28px mark is labelled "home" /
 * "login", so before this component the brand name was never announced in the
 * page body at all; leaving the wordmark readable is a small accessibility gain
 * rather than redundancy.
 *
 * The block is centred but its text is left-aligned: `MYSTERY` sets ~11px wider
 * than `MIXCLUB` at 800/-0.025em, so centring the text staggers both edges by
 * ~5px, which reads as a mistake. Left-aligning puts the whole difference on the
 * right as deliberate rag, which is what the DS does.
 */
export function BrandLockup({ as: Wordmark = "p", children, className = "" }: BrandLockupProps) {
  return (
    <div
      className={`flex flex-col items-center gap-6 sm:flex-row sm:items-start sm:justify-center sm:gap-7 ${className}`}
    >
      <ConcentricRings size={96} spinning accent wordmark onPaper className="shrink-0" />
      <div>
        {/* Every call site of this component is a public page, and those are the
            light surface (ADR 0013) — hence the `ink` ramp unconditionally, with
            no variant prop. If the lockup ever lands on a dark screen, that is
            the moment to add one, not before.

            `club` takes `ink-accent-display` rather than the AA-safe
            `ink-accent`: at clamp(2.5rem, 7vw, 3.5rem) — 40px to 56px, extra
            bold — this is unambiguously WCAG "large text", where the floor is
            3:1 rather than 4.5:1. That buys back the chroma the body-size amber
            has to spend, so the wordmark keeps its punch instead of going
            burnt. Nothing at body size may use that token. */}
        <Wordmark className="text-left font-display text-[clamp(2.5rem,7vw,3.5rem)] font-extrabold uppercase leading-[0.88] tracking-display-hero text-ink">
          mystery
          <br />
          mix<span className="text-ink-accent-display">club</span>
        </Wordmark>
        {children}
      </div>
    </div>
  );
}
