type Service = "youtube" | "spotify" | "appleMusic";

/**
 * A small monochrome mark for a streaming service, sized to sit beside the
 * service name in a playlist row.
 *
 * **Monochrome, and that is a constraint rather than a preference.** These sit
 * on `paper`, and a non-text graphic owes 3:1 there. Measured against white:
 * YouTube red is 4.00:1 and Apple's red 3.58:1, but **Spotify green is 2.59:1
 * and fails**. Brand-coloured marks would therefore be legible for two services
 * and not the third, and the fix — darkening Spotify's green — means altering a
 * trademarked colour, which their brand guidelines do not permit. Drawing them
 * in `ink` keeps the set consistent and legible and sidesteps that entirely.
 *
 * `platformBrand.ts` is not involved: it holds `youtube`/`bandcamp` values for
 * `SourceBadge`, and its own placement table is explicit that brand tints are
 * valid on `card` or darker only. This surface is lighter than any of them.
 *
 * Deliberately simplified silhouettes rather than the official logotypes — they
 * read at 14px, carry no brand colour, and are decorative here: the service is
 * named in text right beside the mark, so nothing depends on recognising them.
 * They are `aria-hidden` for the same reason.
 */
export function ServiceMark({ service, className = "" }: { service: Service; className?: string }) {
  const common = {
    width: 14,
    height: 14,
    viewBox: "0 0 24 24",
    "aria-hidden": true as const,
    className: `shrink-0 ${className}`,
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
