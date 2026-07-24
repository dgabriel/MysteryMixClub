import type { InputHTMLAttributes } from "react";
import { WarningIcon } from "./WarningIcon";

type TextFieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  /** Calm, field-specific validation message. Renders below the input in
   *  Rust with a warning icon and switches the underline to Rust (ADR 0004
   *  — form errors are their own Rust budget, independent of one-per-screen). */
  error?: string | null;
  /** Rust underline without an inline message — for fields that share one
   *  error message rendered by a parent (e.g. a days/hours pair). */
  invalid?: boolean;
};

/**
 * Underline-only input per the style guide — no box, transparent background.
 * Label sits above in 9px ALL CAPS Muted. Underline shifts to Sage on focus,
 * or to Rust when invalid.
 */
export function TextField({
  label,
  id,
  error,
  invalid = false,
  className = "",
  ...rest
}: TextFieldProps) {
  const isInvalid = invalid || Boolean(error);
  const errorId = error ? `${id}-error` : undefined;
  return (
    <label htmlFor={id} className="block">
      <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
        {label}
      </span>
      <input
        id={id}
        {...rest}
        aria-invalid={isInvalid ? true : rest["aria-invalid"]}
        aria-describedby={errorId ?? rest["aria-describedby"]}
        className={[
          "mt-2 w-full bg-transparent font-mono text-[13px] text-ink",
          "border-0 border-b rounded-none px-0 py-1",
          isInvalid ? "border-rust" : "border-ink",
          "placeholder:text-muted",
          "focus:outline-none focus:border-sage",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
      />
      {error ? (
        <p
          id={errorId}
          role="alert"
          className="mt-2 flex items-center gap-1.5 font-mono text-[13px] text-rust"
        >
          <WarningIcon className="shrink-0" />
          {error}
        </p>
      ) : null}
    </label>
  );
}
