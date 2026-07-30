import { WarningIcon } from "./WarningIcon";

/**
 * A form's screen-level validation message — the one that isn't about a single
 * field (rate limits, "you need an invite", a failed submit). Same Rust +
 * warning-icon treatment as TextField's own inline error, because it is the same
 * ADR 0004 category: form errors are their own Rust budget, separate from a
 * screen's one decorative use.
 */
export function FormError({ id, children }: { id?: string; children: string }) {
  return (
    <p
      id={id}
      role="alert"
      className="flex items-center gap-1.5 font-mono text-[13px] text-rust"
    >
      <WarningIcon className="shrink-0" />
      {children}
    </p>
  );
}
