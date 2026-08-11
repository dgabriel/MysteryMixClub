import type { ReactNode } from "react";

/**
 * The "playlists" block: a heading and the ruled stack of service rows.
 *
 * Shared so the four places the mix screen renders playlists cannot drift —
 * they previously carried two different headings ("listen back" in the closed
 * state, "playlist (N)" elsewhere) for the same content.
 */
export function PlaylistsSection({ children }: { children: ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="font-mono uppercase tracking-mono-wide text-meta text-ink-muted">playlists</h2>
      {/* Ruled top and bottom so the block reads as one object on the page
          without needing a surface behind it. */}
      <div className="mt-3 divide-y divide-ink-hairline border-y border-ink-hairline">
        {children}
      </div>
    </section>
  );
}
