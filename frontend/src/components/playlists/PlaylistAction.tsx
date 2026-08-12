import type { ReactNode } from "react";

const ACTION_CLASS =
  "inline-flex items-center gap-1.5 font-mono uppercase tracking-mono text-label text-ink-link underline underline-offset-[3px] transition-colors duration-150 hover:text-ink";

/**
 * The primary affordance on a playlist row — a link out to the service.
 *
 * Sits on the light page, so it takes the `ink` ramp — `ink-link` is 4.55:1 on
 * `paper`, where plain `link` would be 2.42:1 (ADR 0013).
 */
export function PlaylistLink({
  href,
  label,
  children,
}: {
  href: string;
  /** Accessible name, which MUST name the service.
   *
   *  The visible text is deliberately short and identical across rows ("open
   *  playlist") because the service name sits beside it and the row anatomy is
   *  what makes the card scannable. But an accessible name is read without that
   *  context: three links all announcing "open playlist" would be
   *  indistinguishable to anyone tabbing through, which is a WCAG 2.4.4 failure
   *  the visual design does not have. */
  label: string;
  children: ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={label}
      className={ACTION_CLASS}
    >
      {children}
    </a>
  );
}

/**
 * The same affordance for a service that has to *do* something first rather
 * than link out — Apple Music builds the playlist into your own library, so
 * there is nothing to link to until you ask for it.
 *
 * Rendered as a button but styled as the link beside it, deliberately: the row
 * anatomy is what makes the services comparable, and a different-looking
 * control in the action slot would break the pattern for a difference the user
 * does not need to care about until they click.
 */
export function PlaylistButton({
  onClick,
  disabled,
  label,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  /** Accessible name — see `PlaylistLink`. */
  label: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className={`${ACTION_CLASS} disabled:cursor-not-allowed disabled:text-ink-muted disabled:no-underline`}
    >
      {children}
    </button>
  );
}
