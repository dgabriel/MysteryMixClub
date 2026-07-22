import type { ReactNode } from "react";

type Variant = "default" | "accent";

type BadgeProps = {
  variant?: Variant;
  children: ReactNode;
};

const base =
  "inline-block font-mono uppercase tracking-label text-[9px] px-[10px] py-[4px] rounded-[1px]";

const variants: Record<Variant, string> = {
  default: "bg-sage-pale text-sage",
  // Accent uses Rust per the style guide — counts toward the screen's one Rust use.
  accent: "bg-transparent border border-rust text-rust",
};

export function Badge({ variant = "default", children }: BadgeProps) {
  return <span className={[base, variants[variant]].join(" ")}>{children}</span>;
}
