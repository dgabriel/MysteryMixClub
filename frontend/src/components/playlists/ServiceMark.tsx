import { SERVICE_MARK_BRAND, type ServiceMarkKey } from "../../lib/platformBrand";

/**
 * A small brand-coloured mark for a streaming service, sized to sit beside the
 * service name in a playlist row.
 *
 * **Colour is legitimate here specifically because these are decorative.** Each
 * mark sits immediately beside its service's name in text and is `aria-hidden`,
 * so nothing depends on recognising it — and WCAG 1.4.11's 3:1 floor covers
 * graphics *required to understand the content*, which these are not. The
 * numbers would otherwise forbid it: on `paper`, YouTube red is 4.00:1 and
 * Apple red 3.58:1, but Spotify green is only 2.59:1.
 *
 * **Keep the text label.** It is what makes the marks decorative; without it
 * Spotify's green becomes a real contrast failure rather than an exempt one.
 *
 * Values come from `lib/platformBrand.ts` and are applied inline, never as
 * Tailwind classes — they are another company's constants, not design tokens
 * (ADR 0007).
 *
 * Deliberately simplified silhouettes rather than the official logotypes: they
 * have to read at 14px, and reproducing real logotypes brings each service's
 * brand guidelines (clear space, minimum size, permitted lockups) into scope.
 */
export function ServiceMark({
  service,
  className = "",
}: {
  service: ServiceMarkKey;
  className?: string;
}) {
  const common = {
    width: 14,
    height: 14,
    viewBox: "0 0 24 24",
    "aria-hidden": true as const,
    className: `shrink-0 ${className}`,
    // Inline, because a brand value is not a token and Tailwind's JIT cannot
    // see a runtime class string anyway.
    style: { color: SERVICE_MARK_BRAND[service] },
  };

  if (service === "youtube") {
    // Rounded screen with a play triangle.
    return (
      <svg {...common} fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="1.5" y="5" width="21" height="14" rx="4" />
        <path d="M10 9.5v5l4.5-2.5z" fill="currentColor" stroke="none" />
      </svg>
    );
  }

  if (service === "spotify") {
    // Disc with the three signature arcs.
    return (
      <svg {...common} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        <circle cx="12" cy="12" r="10" />
        <path d="M7 9.2c3.4-.9 6.9-.6 9.8 1" />
        <path d="M7.6 12.4c2.8-.7 5.7-.4 8.1.9" />
        <path d="M8.2 15.5c2.2-.5 4.5-.3 6.4.8" />
      </svg>
    );
  }

  // Apple Music: a note inside a rounded square.
  return (
    <svg {...common} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <rect x="2.5" y="2.5" width="19" height="19" rx="5" />
      <path d="M10 16.2V8.6l6-1.3v7.3" />
      <circle cx="8.6" cy="16.4" r="1.6" />
      <circle cx="14.6" cy="15" r="1.6" />
    </svg>
  );
}
