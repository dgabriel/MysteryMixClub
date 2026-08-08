import type { ReactNode } from "react";

type CardProps = {
  /** Render a 3px accent left bar. Amber here is the achievement half of the
   *  accent's category — the winner / most-noted card. */
  accent?: boolean;
  children: ReactNode;
  className?: string;
};

/**
 * The primary content surface: `card` fill, `hairline` edge, `rounded-tile`,
 * padding 20px 24px. It is a Z1 surface wearing a Z2 shadow — cards buy one
 * step of shadow above their lightness step.
 *
 * Deliberately no hover elevation. The style guide raises a card to
 * `shadow-z3` on hover, but this is a non-interactive div with no handlers, so
 * a hover state here would advertise an affordance that does not exist. A
 * clickable card surface opts into `hover:shadow-z3` at its own call site.
 *
 * An optional accent left bar marks a card that requires special attention.
 */
export function Card({ accent = false, children, className = "" }: CardProps) {
  return (
    <div
      className={[
        "relative bg-card border border-hairline rounded-tile px-6 py-5 shadow-z2",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {accent ? (
        <span
          aria-hidden="true"
          className="absolute inset-y-0 left-0 w-[3px] bg-accent rounded-l-tile"
        />
      ) : null}
      {children}
    </div>
  );
}
