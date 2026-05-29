import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost" | "link";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
};

const base =
  "font-mono uppercase tracking-ui text-[11px] transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed";

const variants: Record<Variant, string> = {
  primary:
    "rounded-[2px] px-[22px] py-[10px] bg-sage text-cream hover:bg-sage-light",
  ghost:
    "rounded-[2px] px-[22px] py-[10px] border border-border text-ink hover:bg-sage-pale",
  // Text/link variant uses Rust per the style guide — counts toward the screen's one Rust use.
  link: "text-rust underline underline-offset-[3px] hover:text-ink",
};

export function Button({ variant = "primary", className = "", ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      className={[base, variants[variant], className].filter(Boolean).join(" ")}
    />
  );
}
