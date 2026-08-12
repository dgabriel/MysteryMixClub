import type { ReactNode } from "react";

type PlaylistRowProps = {
  /** The service's own name — the thing you scan the list by. */
  service: string;
  /** A small monochrome mark for the service, shown before its name. Decorative
   *  and `aria-hidden`: the name is right there in text. */
  mark?: ReactNode;
  /** One short line about readiness: "all 4 songs", "3 of 4 songs",
   *  "builds in your library". Kept in ONE register across services on purpose;
   *  see the component note. */
  status: ReactNode;
  /** The primary affordance — a link out, or a button that builds a playlist. */
  action: ReactNode;
  /** Anything subordinate to this service: the songs it could not match, its
   *  fallback link, a consent note. Rendered indented under the row so it can
   *  never be mistaken for a sibling service. */
  children?: ReactNode;
};

/**
 * One service in the listen section, with a fixed anatomy:
 * **service · status · action**, and anything else nested beneath.
 *
 * Rendered directly on the light page (ADR 0013), not inside a card, so it
 * takes the `ink` ramp. Services are separated by a horizontal rule rather than
 * grouped in a surface.
 *
 * The anatomy is the whole point. Before this, the three services each had
 * their own shape — YouTube was a link plus a count, Spotify a link plus a
 * problem sentence plus a *second link* plus a track list, Apple a link plus a
 * caveat — so there was no pattern to learn and every line had to be read.
 * Worse, Spotify's overflow link ("hear the rest on youtube") sat at the same
 * indent and weight as the real YouTube playlist link a few rows above it, and
 * the two were easy to confuse.
 *
 * Two rules for anyone adding a service here:
 *
 * 1. **The status line answers "can I play this right now".** Not what went
 *    wrong, not what it costs — those belong in `children`. Keeping one
 *    question in that slot is what makes the services comparable at a glance.
 * 2. **Anything caused by this service goes in `children`, never beside it.**
 *    A gap, a fallback, a caveat is subordinate; rendering it at top level is
 *    what made the old layout read as one flat list of unrelated links.
 */
export function PlaylistRow({ service, mark, status, action, children }: PlaylistRowProps) {
  return (
    <div className="py-5">
      {/* One line — name, status, action — rather than a two-line stack. A
          service is one fact, and reading it on one line is what lets the eye
          run down the column comparing them. It wraps rather than truncating on
          narrow widths, which is why the status is its own flexible cell. */}
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="flex items-center gap-2 font-mono uppercase tracking-mono-caps text-label text-ink">
          {mark}
          {service}
        </span>
        <span className="min-w-0 flex-1 font-mono text-mini text-ink-muted">{status}</span>
        {action}
      </div>
      {children ? (
        // Indented AND ruled: everything here is caused by the service above it
        // — its missing songs, its fallback link, its caveat. The indent is what
        // stops any of it reading as a service in its own right.
        <div className="mt-3 border-l border-ink-hairline pl-4">{children}</div>
      ) : null}
    </div>
  );
}
