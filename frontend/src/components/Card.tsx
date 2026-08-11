import type { ReactNode } from "react";

/** Colour of the optional 3px left bar. One mechanism, not two — this replaced
 *  a boolean `accent` prop when a second bar colour was needed. */
type Bar = "accent" | "positive";

const BAR: Record<Bar, string> = {
  /** Amber: the achievement half of the accent's category — the winner or
   *  most-noted card. 7.42:1 on `card`. */
  accent: "bg-accent",
  /** Green: a running/live status marker. 6.29:1 on `card`. Distinct from
   *  `accent` on purpose — a status that is true of *most* rows in a list would
   *  spend amber on the default case and stop marking anything. */
  positive: "bg-positive",
};

type CardProps = {
  /** Render a 3px left bar in this colour. Omit for no bar.
   *
   *  The bar is `aria-hidden` and therefore decorative: whatever it signals must
   *  also be carried in text somewhere in the card, or it fails WCAG 1.4.1. */
  bar?: Bar;
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
 * An optional coloured left bar marks a card that requires special attention.
 *
 * **It sets `text-foreground` explicitly, and that is load-bearing** (ADR 0013).
 * A card is a dark island that may now sit on a light page, so its contents must
 * be anchored to the dark ramp rather than inheriting the page's. Most text in
 * here carries no color class of its own and simply inherits — that used to mean
 * `body`'s `text-foreground`, which was right by accident. Under a
 * `PaperSurface` the same text inherited `text-ink` and rendered at 1.65:1 on
 * `card`: every club name on `/home` was very nearly invisible, and it was a
 * contrast audit rather than the eye that caught it.
 */
export function Card({ bar, children, className = "" }: CardProps) {
  return (
    <div
      className={[
        "relative bg-card text-foreground border border-hairline rounded-tile px-6 py-5 shadow-z2",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {bar ? (
        <span
          aria-hidden="true"
          className={`absolute inset-y-0 left-0 w-[3px] rounded-l-tile ${BAR[bar]}`}
        />
      ) : null}
      {children}
    </div>
  );
}
