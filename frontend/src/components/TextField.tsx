import { useState, type InputHTMLAttributes, type Ref } from "react";
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
  /** Opt-in show/hide control for a `type="password"` field, so someone can
   *  check what they typed. Off by default — a field whose value is already
   *  readable has nothing to reveal. */
  revealToggle?: boolean;
  /** Ref to the underlying input, for callers that need to move focus to it.
   *  An explicit prop rather than forwardRef so the component stays a plain
   *  function and every existing call site is untouched. */
  inputRef?: Ref<HTMLInputElement>;
};

function EyeIcon({ revealed }: { revealed: boolean }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M1.5 12S5.5 5 12 5s10.5 7 10.5 7-4 7-10.5 7S1.5 12 1.5 12Z" />
      <circle cx="12" cy="12" r="3" />
      {revealed ? <line x1="4" y1="20" x2="20" y2="4" /> : null}
    </svg>
  );
}

/**
 * Underline-only input per the style guide — no box, transparent background.
 * Label sits above in 9px ALL CAPS Muted. Underline shifts to Sage on focus,
 * or to Rust when invalid.
 *
 * The input is associated by `htmlFor`/`id` rather than by being wrapped in the
 * label, so the optional reveal button isn't interactive content nested inside a
 * label. Every caller passes an `id`.
 */
export function TextField({
  label,
  id,
  error,
  invalid = false,
  revealToggle = false,
  inputRef,
  className = "",
  type,
  ...rest
}: TextFieldProps) {
  const [revealed, setRevealed] = useState(false);
  const isInvalid = invalid || Boolean(error);
  const errorId = error ? `${id}-error` : undefined;
  // Merged, not overridden: a caller-supplied description (a format hint, say)
  // must survive the field going invalid rather than be silently dropped.
  const describedBy =
    [rest["aria-describedby"], errorId].filter(Boolean).join(" ") || undefined;
  // Swapping the type is what actually reveals the value, so the control only
  // means anything on a masked field.
  const canReveal = revealToggle && type === "password";
  return (
    <div className="block">
      <label htmlFor={id} className="block font-mono uppercase tracking-label text-[9px] text-muted">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          ref={inputRef}
          type={canReveal && revealed ? "text" : type}
          {...rest}
          aria-invalid={isInvalid ? true : rest["aria-invalid"]}
          aria-describedby={describedBy}
          className={[
            "mt-2 w-full bg-transparent font-mono text-[13px] text-ink",
            "border-0 border-b rounded-none px-0 py-1",
            canReveal ? "pr-9" : "",
            isInvalid ? "border-rust" : "border-ink",
            "placeholder:text-muted",
            "focus:outline-none focus:border-sage",
            className,
          ]
            .filter(Boolean)
            .join(" ")}
        />
        {canReveal ? (
          <button
            type="button"
            onClick={() => setRevealed((v) => !v)}
            aria-label={revealed ? "hide password" : "show password"}
            className="absolute bottom-0 right-0 flex h-8 w-8 items-center justify-center text-muted hover:text-ink"
          >
            <EyeIcon revealed={revealed} />
          </button>
        ) : null}
      </div>
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
    </div>
  );
}
