import type { InputHTMLAttributes } from "react";

type TextFieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
};

/**
 * Underline-only input per the style guide — no box, transparent background.
 * Label sits above in 9px ALL CAPS Muted. Underline shifts to Sage on focus.
 */
export function TextField({ label, id, className = "", ...rest }: TextFieldProps) {
  return (
    <label htmlFor={id} className="block">
      <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
        {label}
      </span>
      <input
        id={id}
        {...rest}
        className={[
          "mt-2 w-full bg-transparent font-mono text-[13px] text-ink",
          "border-0 border-b border-ink rounded-none px-0 py-1",
          "placeholder:text-muted",
          "focus:outline-none focus:border-sage",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
      />
    </label>
  );
}
