export type SourceOnlyTrack = {
  submission_id: string;
  title: string;
  artist: string;
  source: "youtube" | "bandcamp";
  source_url: string;
};

const TITLE_LINK_CLASS =
  "font-mono text-[11px] font-light text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink";

/**
 * One unified list of a mix's Bandcamp/YouTube-only picks — the tracks that,
 * having no catalog ISRC (MYS-201), may not appear on the generated Spotify or
 * Apple playlists. Sits above the playlist links, calm and informational: a
 * muted label over a muted list, never the screen's Rust signal. Each title
 * links out to its Bandcamp/YouTube page. Renders nothing when there are none.
 */
export function SourceOnlyTracks({ tracks }: { tracks: SourceOnlyTrack[] }) {
  if (tracks.length === 0) return null;
  return (
    <div className="mb-3 border-l-2 border-sage-light pl-3">
      <p className="font-mono uppercase tracking-label text-[9px] text-muted">
        bandcamp or YouTube only tracks that may not appear on your playlists
      </p>
      <ul className="mt-2 space-y-1">
        {tracks.map((t) => (
          <li key={t.submission_id} className="font-mono text-[11px] font-light text-muted">
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
