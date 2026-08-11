import type { ReactNode } from "react";

type Variant = "default" | "accent" | "positive" | "strong";

type BadgeProps = {
  variant?: Variant;
  children: ReactNode;
};

const base = "inline-block font-mono uppercase tracking-mono text-mini px-2 py-1 rounded-hair";

/**
 * Four weights, and they are a deliberate ladder rather than a palette. A list
 * of mixes uses three of them at once to make state legible at a glance:
 * `positive` (live) reads loudest, `strong` (upcoming) sits in the middle, and
 * `default` (finished) is quietest. Pick by how much attention the state
 * deserves, not by which colour looks nice.
 */
const variants: Record<Variant, string> = {
  // An inset chip inside a card is the literal definition of `tile`. The label
  // is `muted-foreground` (5.34:1) rather than `foreground`, so a state chip
  // stays quiet and does not compete with the card's own title. The `hairline`
  // edge is load-bearing: the tile-on-card lightness step is only 1.126:1
  // (card 0.00408, tile 0.01087), so without it the chip reads as a floating
  // word rather than a chip.
  default: "bg-tile text-muted-foreground border border-hairline",
  // Amber here is achievement, not decoration — a rank-1 or winner marker.
  // 6.92:1.
  accent: "bg-accent-surface text-accent border border-accent-hairline",
  // The loud end of the ladder: a SOLID fill, not a tint, for a state that is
  // live and scarce — currently the one active mix in a club. Near-black on
  // green is 6.72:1, and the fill itself is 6.29:1 against `card`, so the chip
  // reads as an object rather than a word. No border: the fill is the edge.
  positive: "bg-positive text-accent-foreground",
  // A neutral chip that still wants to be read — `foreground` at 15.84:1 on
  // `tile` rather than `default`'s muted 5.34:1. The middle rung: brighter than
  // a finished thing, quieter than a live one.
  strong: "bg-tile text-foreground border border-hairline",
};

export function Badge({ variant = "default", children }: BadgeProps) {
  return <span className={[base, variants[variant]].join(" ")}>{children}</span>;
}
