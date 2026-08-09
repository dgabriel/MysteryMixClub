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
 * The brand lockup: the spinning disc over the two-line wordmark, typeset as the
 * design system's hero (DS `App.tsx:428-437`).
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
export function BrandLockup({
  as: Wordmark = "p",
  children,
  className = "",
}: BrandLockupProps) {
  return (
    <div className={className}>
      <ConcentricRings size={96} spinning accent wordmark className="mx-auto" />
      <div className="mt-8 mx-auto w-fit">
        <Wordmark className="text-left font-display text-[clamp(2.5rem,8vw,4.5rem)] font-extrabold uppercase leading-[0.88] tracking-display-hero text-foreground">
          mystery
          <br />
          mix<span className="text-accent">club</span>
        </Wordmark>
        {children}
      </div>
    </div>
  );
}
