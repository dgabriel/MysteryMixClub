import { WarningIcon } from "./WarningIcon";

/**
 * A form's screen-level validation message — the one that isn't about a single
 * field (rate limits, "you need an invite", a failed submit). Same
 * `destructive-text` + warning-icon treatment as TextField's own inline error,
 * because it is the same ADR 0004 category: form errors are their own color
 * category, separate from the accent entirely.
 *
 * `destructive-text`, never `destructive` — `destructive` is a fill color and
 * measures 3.57:1 as text on `card`, an outright AA failure. This renders on
 * whatever surface the form sits on: 6.79:1 on `card`, and it must not be
 * placed on `sheet`.
 *
 * `onPaper` switches to the light-surface ramp (ADR 0013). It is not optional
 * polish on the public pages: `destructive-text` measures 2.86:1 on `paper`, so
 * the sign-in form's own error messages would fail AA — the one message on the
 * screen a user most needs to be able to read.
 */
export function FormError({
  id,
  onPaper = false,
  children,
}: {
  id?: string;
  onPaper?: boolean;
  children: string;
}) {
  return (
    <p
      id={id}
      role="alert"
      className={`flex items-center gap-1.5 font-mono text-sm ${
        onPaper ? "text-ink-destructive" : "text-destructive-text"
      }`}
    >
      <WarningIcon className="shrink-0" />
      {children}
    </p>
  );
}
