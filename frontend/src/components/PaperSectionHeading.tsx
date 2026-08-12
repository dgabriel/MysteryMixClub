import type { ReactNode } from "react";

/**
 * A **major** section heading on a light (`paper`) page — display type, ink,
 * sized just under the page's own `h1`.
 *
 * The mix screen has two tiers of heading and they were rendering identically:
 * "playlists" and "cast your votes" — the two things the screen is actually for
 * — sat at the same 8.8px grey mono as "admin tools" and "songs that may not be
 * on all playlists". Everything looked like a footnote, so nothing read as a
 * landmark.
 *
 * The rule is about rank, not decoration:
 *
 * - **This component** is for a section a reader navigates *to*. Big Shoulders
 *   at `1.375rem`/700, `text-ink` — the same treatment a club card's title
 *   gets, one step below the page `h1` at `1.75rem`.
 * - **`font-mono uppercase tracking-mono-wide text-meta text-ink-muted`** stays
 *   the minor tier, for labels *about* a section: "admin tools", the
 *   maybe-missing list, note counts.
 *
 * If a new section can't decide which tier it belongs to, it is minor.
 */
export function PaperSectionHeading({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <h2
      className={`font-display text-[1.375rem] font-bold uppercase leading-none tracking-display-snug text-ink ${className}`}
    >
      {children}
    </h2>
  );
}
