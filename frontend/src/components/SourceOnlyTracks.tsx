export type SourceOnlyTrack = {
  submission_id: string;
  title: string;
  artist: string;
  source: "youtube" | "bandcamp";
  source_url: string;
};

/**
 * The title link on each row. Neutral at rest, amber only on hover.
 *
 * This list is one row per source-only pick and is unbounded — a mix can be
 * all-Bandcamp — so an `accent` resting color would put amber on every row and
 * read as the list's styling rather than as a signal. That is amber as
 * pattern, which the category rule forbids however in-category a single
 * link would be. Hover is transient and can only apply to one row at a time,
 * so it keeps the accent. Same conclusion R8/R10 reached for their per-row
 * controls.
 */
const TITLE_LINK_CLASS =
  "font-mono text-meta text-foreground underline underline-offset-[3px] transition-colors duration-150 hover:text-accent";

/**
 * One unified list of a mix's Bandcamp/YouTube-only picks — the tracks that,
 * having no catalog ISRC (MYS-201), may not appear on the generated Spotify or
 * Apple playlists. Sits above the playlist links, calm and informational: a
 * mono label over a muted list, and never the screen's accent. Each title
 * links out to its Bandcamp/YouTube page. Renders nothing when there are none.
 *
 * The left rule is a `hairline` — a decorative divider, not a control, so the
 * ~1.2:1 edge is fine here (WCAG 1.4.11 only binds when a boundary is the sole
 * means of identifying a control, and each title link identifies itself).
 */
export function SourceOnlyTracks({ tracks }: { tracks: SourceOnlyTrack[] }) {
  if (tracks.length === 0) return null;
  return (
    <div className="mb-3 border-l-2 border-hairline pl-3">
      <p className="font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
        bandcamp or YouTube only tracks that may not appear on your playlists
      </p>
      <ul className="mt-2 space-y-1">
        {tracks.map((t) => (
          <li key={t.submission_id} className="font-mono text-meta text-muted-foreground">
            <a
              href={t.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className={TITLE_LINK_CLASS}
            >
              {t.title}
            </a>
            {t.artist ? ` · ${t.artist}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}
