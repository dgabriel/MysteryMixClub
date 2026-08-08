import type { ReactNode } from "react";

type Variant = "default" | "accent";

type BadgeProps = {
  variant?: Variant;
  children: ReactNode;
};

const base =
  "inline-block font-mono uppercase tracking-mono text-mini px-2 py-1 rounded-hair";

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
};

export function Badge({ variant = "default", children }: BadgeProps) {
  return <span className={[base, variants[variant]].join(" ")}>{children}</span>;
}
