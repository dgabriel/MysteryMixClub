import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost" | "link" | "destructive";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  /** The button is on the light public surface (`paper`, ADR 0013).
   *
   *  Only the two variants whose color IS text change: `link` (2.42:1 on paper
   *  as `text-link` — an AA failure) and the shared disabled label. `primary`,
   *  `ghost` and `destructive` are fills carrying their own foreground, so they
   *  are already correct on any surface and are deliberately left alone. */
  onPaper?: boolean;
};

/**
 * Mono button type per the style guide: `text-label`, uppercase,
 * `tracking-mono`, `rounded-hair`. Buttons are inner elements — they sit on a
 * surface rather than being one, so none of them carries a shadow.
 *
 * Padding is `px-4 py-2`, down from `px-6 py-3` (Dawn, 2026-08-11 — filled
 * buttons were dominating the screens they sat on). That lands a button at
 * ~29px tall, which still clears the 24x24 CSS-px floor WCAG 2.5.8 sets for a
 * target; do not shrink the vertical padding further without re-checking it.
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
  "font-mono uppercase tracking-mono text-label transition-colors duration-150 disabled:cursor-not-allowed disabled:bg-transparent disabled:border-transparent";
// The disabled label is the one part of `base` that is a bare foreground color,
// so it needs the ramp too — `muted-foreground` is 3.23:1 on paper.
const disabledLabel = {
  dark: "disabled:text-muted-foreground",
  paper: "disabled:text-ink-muted",
};

const variants: Record<Variant, string> = {
  // The primary CTA — an `accent` fill. Amber's category is action, and this is
  // the action.
  primary: "rounded-hair px-4 py-2 bg-accent text-accent-foreground hover:bg-accent-hover",
  // Secondary. A `tile` fill, not a transparent box: a `hairline` edge alone is
  // ~1.1:1 and cannot be the sole thing identifying a control (WCAG 1.4.11).
  // Hover lifts one surface step to `panel` rather than adding a shadow, since
  // a flush button that grew a shadow would read as floating.
  ghost: "rounded-hair px-4 py-2 bg-tile text-foreground border border-hairline hover:bg-panel",
  // Danger. Separate from `link` so a delete affordance reads as danger rather
  // than as an ordinary action — `destructive` is a fill color and never text.
  destructive:
    "rounded-hair px-4 py-2 bg-destructive text-destructive-foreground hover:bg-destructive-hover",
  // Text button. Blue because it is navigation-shaped; always underlined, so
  // the affordance never rests on hue alone.
  link: "text-link underline underline-offset-[3px] hover:text-foreground",
};

// `link` and `ghost` differ on paper.
//
// `ghost` is the important one, and it was a real bug: its `tile` fill is a
// *subtle lift* on a dark page (1.20:1 against `floor`) but a **black slab** on
// paper (17.25:1). That inverted the hierarchy wherever both appeared — a
// secondary control outweighing the amber primary beside it by roughly six
// times. On paper it becomes an outlined button instead: no fill, an
// `ink-muted` edge at 4.67:1 so it still reads as a control, and a faint wash
// on hover.
const paperVariants: Partial<Record<Variant, string>> = {
  link: "text-ink-link underline underline-offset-[3px] hover:text-ink",
  ghost:
    "rounded-hair px-4 py-2 bg-transparent text-ink border border-ink-muted hover:bg-ink-hairline",
};

export function Button({
  variant = "primary",
  onPaper = false,
  className = "",
  ...rest
}: ButtonProps) {
  const variantClass = (onPaper ? paperVariants[variant] : undefined) ?? variants[variant];
  return (
    <button
      {...rest}
      className={[base, onPaper ? disabledLabel.paper : disabledLabel.dark, variantClass, className]
        .filter(Boolean)
        .join(" ")}
    />
  );
}
