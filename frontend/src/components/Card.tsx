import type { ReactNode } from "react";

type CardProps = {
  /** Render a 3px Rust left accent bar — counts as the screen's one Rust use. */
  accent?: boolean;
  children: ReactNode;
  className?: string;
};

/**
 * Surface card lifted from the cream background. Border per the style guide,
 * 3px rounded, padding 20px 24px. An optional Rust left accent bar marks a
 * card that requires special attention.
 */
export function Card({ accent = false, children, className = "" }: CardProps) {
  return (
    <div
      className={[
        "relative bg-white border border-border rounded-[3px] px-6 py-5",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {accent ? (
        <span
          aria-hidden="true"
          className="absolute inset-y-0 left-0 w-[3px] bg-rust rounded-l-[3px]"
        />
      ) : null}
      {children}
    </div>
  );
}
