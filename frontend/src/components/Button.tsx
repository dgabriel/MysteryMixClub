import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost" | "link" | "destructive";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
};

/**
 * Mono button type per the style guide: `text-label`, uppercase,
 * `tracking-mono`, `rounded-hair`. Buttons are inner elements — they sit on a
 * surface rather than being one, so none of them carries a shadow.
 *
 * Disabled removes the box entirely — no fill, no edge — and drops the label
 * to `muted-foreground`. Two things ruled out the alternatives:
 *
 * - `disabled:opacity-50` (the old treatment) puts a primary button's
 *   near-black label at 2.72:1. Unreadable.
 * - A `tile` fill is what an *enabled* ghost button already is, so a disabled
 *   primary sitting next to a ghost "cancel" would read as a second secondary
 *   button rather than as unavailable.
 *
 * Removing the fill is the only direction that recedes without brightening:
 * on a near-black page nothing is darker than the surface to recede *into*.
 * The label stays at 6.01:1 on `card` / 6.38:1 on `floor`, against the ghost's
 * 15.84:1 — a 2.6x drop plus the loss of the fill and edge, which is the
 * distinction that does not depend on `cursor-not-allowed` (that cue does not
 * exist on touch, so it is a supplement, never the signal).
 *
 * `border-transparent` rather than dropping the border keeps the border-box
 * geometry identical, so a ghost button does not resize when it disables.
 * Tailwind orders `disabled:` after `hover:`, so a disabled button cannot pick
 * up a hover fill.
 */
const base =
  "font-mono uppercase tracking-mono text-label transition-colors duration-150 disabled:cursor-not-allowed disabled:bg-transparent disabled:border-transparent disabled:text-muted-foreground";

const variants: Record<Variant, string> = {
  // The primary CTA — an `accent` fill. Amber's category is action, and this is
  // the action.
  primary:
    "rounded-hair px-6 py-3 bg-accent text-accent-foreground hover:bg-accent-hover",
  // Secondary. A `tile` fill, not a transparent box: a `hairline` edge alone is
  // ~1.1:1 and cannot be the sole thing identifying a control (WCAG 1.4.11).
  // Hover lifts one surface step to `panel` rather than adding a shadow, since
  // a flush button that grew a shadow would read as floating.
  ghost:
    "rounded-hair px-6 py-3 bg-tile text-foreground border border-hairline hover:bg-panel",
  // Danger. Separate from `link` so a delete affordance reads as danger rather
  // than as an ordinary action — `destructive` is a fill color and never text.
  destructive:
    "rounded-hair px-6 py-3 bg-destructive text-destructive-foreground hover:bg-destructive-hover",
  // Text button. Amber because a text button is still an action.
  link: "text-link underline underline-offset-[3px] hover:text-foreground",
};

export function Button({ variant = "primary", className = "", ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      className={[base, variants[variant], className].filter(Boolean).join(" ")}
    />
  );
}
